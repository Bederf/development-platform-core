"""Durable Founder confirmation context for bounded development decisions.

This is deliberately separate from ``development-workflow.v1``.  It records
the Founder authority context once at session start and allows a concise
confirmation only for a prepared decision whose exact phase, specification,
action, scope and exclusions are bound to that session.

It is not an acceptance authority and cannot bypass phase resolution, tests,
independent review, technical gates, or production/consumer controls.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


class FounderAcceptanceSessionError(ValueError):
    """Raised when a session or concise confirmation is invalid."""


def canonical_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("digest", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_session(value: Mapping[str, Any]) -> None:
    schema_path = Path(__file__).parents[1] / "contracts" / "founder-acceptance-session.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(dict(value)),
        key=lambda error: list(error.path),
    )
    if errors:
        raise FounderAcceptanceSessionError(f"invalid Founder acceptance session: {errors[0].message}")
    if canonical_digest(value) != value.get("digest"):
        raise FounderAcceptanceSessionError("Founder acceptance session digest is invalid")
    bindings = {item["phase_id"] for item in value["scope"]["specification_bindings"]}
    if bindings != set(value["scope"]["phase_ids"]):
        raise FounderAcceptanceSessionError("session bindings do not cover exactly the declared phases")


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


class FounderAcceptanceSession:
    """Open one attributable context, then confirm exact prepared decisions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def open(
        self,
        *,
        session_id: str,
        authority_subject: str,
        authentication: Mapping[str, Any],
        authority_basis_refs: list[str],
        authority_roles: Mapping[str, Any],
        phase_ids: list[str],
        allowed_actions: list[str],
        specification_bindings: list[Mapping[str, Any]],
        exclusions: list[str],
        operational_custody: Mapping[str, Any] | None = None,
        opened_at: str | None = None,
    ) -> dict[str, Any]:
        if self.path.exists():
            existing = self.load()
            if existing["status"] == "OPEN":
                if existing["session_id"] == session_id:
                    return existing
                raise FounderAcceptanceSessionError("an acceptance session is already open")
            raise FounderAcceptanceSessionError("acceptance session cannot be reopened")
        if not session_id.strip() or not authority_subject.strip():
            raise FounderAcceptanceSessionError("session identity and authority subject are required")
        value: dict[str, Any] = {
            "schema": "founder-acceptance-session.v1",
            "session_id": session_id,
            "authority_subject": authority_subject,
            "authentication": dict(authentication),
            "authority_basis_refs": list(dict.fromkeys(authority_basis_refs)),
            "authority_roles": dict(authority_roles),
            "scope": {
                "phase_ids": list(dict.fromkeys(phase_ids)),
                "allowed_actions": list(dict.fromkeys(allowed_actions)),
                "specification_bindings": [dict(item) for item in specification_bindings],
            },
            "exclusions": list(dict.fromkeys(exclusions)),
            "confirmation_policy": {
                "accepted_tokens": ["yes"],
                "requires_prepared_decision": True,
                "does_not_bypass_gates": True,
            },
            "opened_at": opened_at or datetime.now(UTC).isoformat(),
            "status": "OPEN",
        }
        if operational_custody is not None:
            value["operational_custody"] = dict(operational_custody)
        value["digest"] = canonical_digest(value)
        _validate_session(value)
        _write_atomic(self.path, value)
        return value

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FounderAcceptanceSessionError("acceptance session is unreadable") from exc
        if not isinstance(value, dict):
            raise FounderAcceptanceSessionError("acceptance session must be an object")
        _validate_session(value)
        return value

    def prepare(self, decision: Mapping[str, Any]) -> dict[str, Any]:
        session = self.load()
        if session["status"] != "OPEN":
            raise FounderAcceptanceSessionError("acceptance session is not open")
        required = {"decision_id", "phase_id", "specification_ref", "specification_hash", "action", "exclusions", "independent_review"}
        if not required.issubset(decision):
            raise FounderAcceptanceSessionError("prepared decision is incomplete")
        binding = next((item for item in session["scope"]["specification_bindings"] if item["phase_id"] == decision["phase_id"]), None)
        if binding is None or any(decision[key] != binding[key] for key in ("phase_id", "specification_ref", "specification_hash")):
            raise FounderAcceptanceSessionError("prepared decision is not bound to the session specification")
        review_policy = decision["independent_review"]
        if (
            not isinstance(review_policy, Mapping)
            or review_policy.get("required") != binding["review_required"]
            or review_policy.get("provider_ref") != binding["review_provider_ref"]
        ):
            raise FounderAcceptanceSessionError("prepared decision review policy does not match the phase risk policy")
        if decision["phase_id"] not in session["scope"]["phase_ids"] or decision["action"] not in session["scope"]["allowed_actions"]:
            raise FounderAcceptanceSessionError("prepared decision is outside the session scope")
        if set(decision["exclusions"]) != set(session["exclusions"]):
            raise FounderAcceptanceSessionError("prepared decision exclusions do not match the session")
        prepared = dict(decision)
        # Re-validation must be idempotent: these binding fields are produced
        # by this method and are not part of the caller's decision payload.
        prepared.pop("session_id", None)
        prepared.pop("session_digest", None)
        prepared.pop("operational_custody_digest", None)
        prepared.pop("prepared_digest", None)
        prepared["session_id"] = session["session_id"]
        prepared["session_digest"] = session["digest"]
        if "operational_custody" in session:
            prepared["operational_custody_digest"] = canonical_digest(session["operational_custody"])
        prepared["prepared_digest"] = canonical_digest(prepared)
        return prepared

    def confirm(self, prepared: Mapping[str, Any], response: str) -> dict[str, Any]:
        session = self.load()
        if session["status"] != "OPEN":
            raise FounderAcceptanceSessionError("acceptance session is not open")
        if response.strip().lower() != "yes":
            raise FounderAcceptanceSessionError("only an explicit yes confirms a prepared decision")
        expected = self.prepare(prepared)
        if dict(prepared) != expected:
            raise FounderAcceptanceSessionError("prepared decision is not content-bound to this session")
        confirmation = {
            "schema": "founder-acceptance-confirmation.v1",
            "confirmation_id": f"confirmation:{prepared['decision_id']}",
            "session_id": session["session_id"],
            "session_digest": session["digest"],
            "prepared_digest": prepared["prepared_digest"],
            "decision_id": prepared["decision_id"],
            "response": "yes",
            "confirmed_by": session["authority_subject"],
            "confirmed_at": datetime.now(UTC).isoformat(),
            "authority_boundary": {
                "gates_still_required": True,
                "independent_review_required": prepared["independent_review"]["required"],
                "independent_review_still_required": prepared["independent_review"]["required"],
                "production_authority_granted": False,
            },
        }
        confirmation["digest"] = canonical_digest(confirmation)
        record_path = self.path.with_name(self.path.stem + "-confirmations.jsonl")
        with record_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(confirmation, sort_keys=True) + "\n")
        return confirmation
