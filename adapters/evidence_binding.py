"""Core-owned binding and lifecycle for risk-selected review evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker


class EvidenceBindingError(ValueError):
    """Raised when a review evidence binding cannot be trusted."""


_SCHEMA_PATH = Path(__file__).parents[1] / "contracts" / "evidence-binding.v1.schema.json"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_bytes(value: Any) -> bytes:
    """Return the one deterministic representation used for evidence digests."""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceBindingError("evidence is not canonically serializable") from exc


def digest_for(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def _identity(ref_id: str, version: str, value: Any) -> dict[str, str]:
    if not isinstance(ref_id, str) or not ref_id.strip() or not isinstance(version, str) or not version.strip():
        raise EvidenceBindingError("identity reference requires id and version")
    return {"id": ref_id, "version": version, "digest": digest_for(value)}


def _evidence_ref(ref: str, value: Any) -> dict[str, str]:
    if not isinstance(ref, str) or not ref.strip():
        raise EvidenceBindingError("evidence reference is required")
    return {"ref": ref, "canonicalization": "json-sorted-utf8-v1", "digest": digest_for(value)}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_source_schema(value: Mapping[str, Any], schema_name: str) -> None:
    schema_path = Path(__file__).parents[1] / "contracts" / schema_name
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceBindingError(f"source contract is unavailable: {schema_name}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(dict(value)),
        key=lambda error: list(error.path),
    )
    if errors:
        raise EvidenceBindingError(f"invalid {schema_name}: {errors[0].message}")


def validate_binding(binding: Mapping[str, Any], *, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate schema, lifecycle state, cross-record identities, and digests."""

    value = dict(binding)
    errors = sorted(
        Draft202012Validator(_load_schema(), format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise EvidenceBindingError(f"invalid evidence-binding.v1: {errors[0].message}")
    if value["binding_digest"] != digest_for({key: item for key, item in value.items() if key != "binding_digest"}):
        raise EvidenceBindingError("binding digest does not match canonical binding")

    if value["record_type"] == "evidence_binding":
        _validate_current_binding(value, evidence=evidence)
    else:
        _validate_historical_binding(value)
    return value


def _validate_current_binding(binding: Mapping[str, Any], *, evidence: Mapping[str, Any] | None) -> None:
    subject = binding["subject"]
    review = binding["review"]
    if not all(isinstance(subject[key], str) and subject[key].strip() for key in ("task_ref", "implementation_revision_ref", "implementation_context_id")):
        raise EvidenceBindingError("current binding requires task, revision, and implementation context")
    if not isinstance(review["reviewer_ref"], str) or not review["reviewer_ref"].strip():
        raise EvidenceBindingError("current binding requires reviewer_ref")
    if not isinstance(review["reviewer_context_id"], str) or not review["reviewer_context_id"].strip():
        raise EvidenceBindingError("current binding requires reviewer context")
    if not isinstance(review["core_invocation_id"], str) or not review["core_invocation_id"].strip():
        raise EvidenceBindingError("current binding requires Core invocation identity")
    if review["independence_required"] and review["reviewer_context_id"] == subject["implementation_context_id"]:
        raise EvidenceBindingError("implementation and reviewer contexts must differ")
    provider = review["provider"]
    if not isinstance(provider["provider_ref"], str) or not provider["provider_ref"].strip():
        raise EvidenceBindingError("provider identity is required")
    if not isinstance(binding["lifecycle"]["policy_ref"], str) or not binding["lifecycle"]["policy_ref"].strip():
        raise EvidenceBindingError("lifecycle policy reference is required")
    evidence_refs = binding["evidence"]
    if evidence_refs["raw"] is None or evidence_refs["review_result"] is None or evidence_refs["review_cycle"] is None:
        raise EvidenceBindingError("current binding requires raw, result, and cycle evidence")
    if binding["lifecycle"]["state"] == "ACTIVE" and any(
        binding["lifecycle"][key] is not None for key in ("eligible_at", "eligibility_ref", "eligibility_evaluated_by", "deletion_authorization_ref", "deletion_authorized_by", "deletion_receipt")
    ):
        raise EvidenceBindingError("active binding cannot contain disposition evidence")
    if binding["binding_status"] != binding["lifecycle"]["state"]:
        raise EvidenceBindingError("binding and lifecycle states must match")
    _validate_state_requirements(binding)
    if evidence is not None:
        _verify_evidence_digests(binding, evidence)
    _verify_cross_references(binding, evidence)


def _validate_state_requirements(binding: Mapping[str, Any]) -> None:
    lifecycle = binding["lifecycle"]
    state = lifecycle["state"]
    if state == "ELIGIBLE_FOR_DISPOSITION" and not lifecycle["eligibility_ref"]:
        raise EvidenceBindingError("eligibility requires an eligibility reference")
    if state == "ELIGIBLE_FOR_DISPOSITION" and not lifecycle["eligibility_evaluated_by"]:
        raise EvidenceBindingError("eligibility requires an evaluator")
    if state == "DELETION_AUTHORIZED" and not lifecycle["deletion_authorization_ref"]:
        raise EvidenceBindingError("deletion authorization requires an authority reference")
    if state == "DELETION_AUTHORIZED" and not lifecycle["deletion_authorized_by"]:
        raise EvidenceBindingError("deletion authorization requires an authorizer")
    if state == "DELETED" and not lifecycle["deletion_receipt"]:
        raise EvidenceBindingError("deleted binding requires a deletion receipt")
    if state != "DELETED" and lifecycle["deletion_receipt"] is not None:
        raise EvidenceBindingError("deletion receipt is only valid after deletion")


def _verify_cross_references(binding: Mapping[str, Any], evidence: Mapping[str, Any] | None) -> None:
    if evidence is None:
        return
    request = evidence.get("request")
    result = evidence.get("review_result")
    cycle = evidence.get("review_cycle")
    if not isinstance(request, Mapping) or not isinstance(result, Mapping) or not isinstance(cycle, Mapping):
        raise EvidenceBindingError("request, review result, and review cycle evidence are required")
    subject = binding["subject"]
    if request.get("request_id") != binding["review"]["request_ref"]["id"]:
        raise EvidenceBindingError("request identity does not match binding")
    if request.get("revision_ref") != subject["implementation_revision_ref"] or result.get("attempt_ref") != subject["implementation_revision_ref"]:
        raise EvidenceBindingError("implementation revision does not match review evidence")
    if result.get("review_id") != binding["evidence"]["review_result"]["id"]:
        raise EvidenceBindingError("review result identity does not match binding")
    if cycle.get("cycle_id") != binding["evidence"]["review_cycle"]["id"] or cycle.get("review_result_ref") != result.get("review_id"):
        raise EvidenceBindingError("review cycle does not match review result")


def _verify_evidence_digests(binding: Mapping[str, Any], evidence: Mapping[str, Any]) -> None:
    request = evidence.get("request")
    result = evidence.get("review_result")
    cycle = evidence.get("review_cycle")
    raw = evidence.get("raw")
    if digest_for(request) != binding["review"]["request_ref"]["digest"]:
        raise EvidenceBindingError("request digest mismatch")
    if digest_for(result) != binding["evidence"]["review_result"]["digest"]:
        raise EvidenceBindingError("review result digest mismatch")
    if digest_for(cycle) != binding["evidence"]["review_cycle"]["digest"]:
        raise EvidenceBindingError("review cycle digest mismatch")
    if digest_for(raw) != binding["evidence"]["raw"]["digest"]:
        raise EvidenceBindingError("raw evidence digest mismatch")


def _validate_historical_binding(binding: Mapping[str, Any]) -> None:
    if binding["binding_status"] not in {"BOUND", "PARTIALLY_BOUND", "UNBOUND_INSUFFICIENT"}:
        raise EvidenceBindingError("historical reconciliation has an invalid status")
    if binding["lifecycle"]["state"] != "ACTIVE":
        raise EvidenceBindingError("historical reconciliation cannot authorize lifecycle deletion")


def build_binding(
    request: Mapping[str, Any],
    review_result: Mapping[str, Any],
    review_cycle: Mapping[str, Any],
    *,
    raw_evidence: Any,
    raw_evidence_ref: str,
    implementation_context_id: str,
    reviewer_context_id: str,
    core_invocation_id: str,
    provider: Mapping[str, Any],
    policy_ref: str,
    binding_id: str | None = None,
    acceptance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a binding from source evidence, computing every digest internally."""

    if not isinstance(request, Mapping) or not isinstance(review_result, Mapping) or not isinstance(review_cycle, Mapping):
        raise EvidenceBindingError("request, review result, and review cycle must be objects")
    _validate_source_schema(request, "independent-review-request.v1.schema.json")
    _validate_source_schema(review_result, "code-review-result.v1.schema.json")
    _validate_source_schema(review_cycle, "review-cycle.v1.schema.json")
    if request.get("independence_required") is not True:
        raise EvidenceBindingError("evidence binding requires an independent review request")
    if request.get("reviewer_ref") != provider.get("reviewer_ref", request.get("reviewer_ref")):
        raise EvidenceBindingError("reviewer identity does not match request")
    if review_result.get("attempt_ref") != request.get("revision_ref"):
        raise EvidenceBindingError("review result revision does not match request")
    if review_cycle.get("revision_ref") != request.get("revision_ref"):
        raise EvidenceBindingError("review cycle revision does not match request")
    if not implementation_context_id or not reviewer_context_id or implementation_context_id == reviewer_context_id:
        raise EvidenceBindingError("distinct implementation and reviewer contexts are required")
    if not core_invocation_id:
        raise EvidenceBindingError("Core invocation identity is required")
    if not isinstance(provider.get("provider_ref"), str) or not provider["provider_ref"].strip():
        raise EvidenceBindingError("provider identity is required")
    result_id = str(review_result.get("review_id") or "")
    cycle_id = str(review_cycle.get("cycle_id") or "")
    if not result_id or not cycle_id:
        raise EvidenceBindingError("review result and cycle identities are required")
    binding = {
        "schema": "evidence-binding.v1",
        "binding_id": binding_id or f"evidence-binding-{uuid4().hex}",
        "record_type": "evidence_binding",
        "binding_status": "ACTIVE",
        "subject": {
            "task_ref": str(request.get("task_ref") or ""),
            "implementation_revision_ref": str(request.get("revision_ref") or ""),
            "implementation_context_id": implementation_context_id,
        },
        "review": {
            "request_ref": _identity(str(request.get("request_id") or ""), "1", request),
            "reviewer_ref": str(request.get("reviewer_ref") or ""),
            "reviewer_context_id": reviewer_context_id,
            "independence_required": True,
            "core_invocation_id": core_invocation_id,
            "provider": {
                "provider_ref": provider.get("provider_ref"),
                "model": provider.get("model"),
                "provider_request_id": provider.get("provider_request_id"),
                "provider_invocation_id": provider.get("provider_invocation_id"),
            },
        },
        "evidence": {
            "raw": _evidence_ref(raw_evidence_ref, raw_evidence),
            "review_result": _identity(result_id, "1", review_result),
            "review_cycle": _identity(cycle_id, "1", review_cycle),
            "acceptance": _identity(str(acceptance["acceptance_ref"]), "1", acceptance) if acceptance else None,
        },
        "lifecycle": {
            "retention_basis": "lifecycle-bound",
            "policy_ref": policy_ref,
            "state": "ACTIVE",
            "eligible_at": None,
            "eligibility_ref": None,
            "eligibility_evaluated_by": None,
            "deletion_authorization_ref": None,
            "deletion_authorized_by": None,
            "deletion_receipt": None,
        },
        "historical_reconciliation": {
            "status": "NOT_APPLICABLE",
            "missing_fields": [],
            "limitations": [],
            "reconciled_at": None,
        },
    }
    binding["binding_digest"] = digest_for(binding)
    return validate_binding(binding, evidence={"request": request, "raw": raw_evidence, "review_result": review_result, "review_cycle": review_cycle})


def reconcile_historical(*, source_ref: str, fields: Mapping[str, Any], relevant: bool, limitations: list[str] | None = None) -> dict[str, Any]:
    """Classify historical evidence without fabricating unavailable provenance."""

    required = ("request_id", "implementation_revision_ref", "reviewer_context_id", "review_result_ref", "review_cycle_ref")
    missing = [field for field in required if not fields.get(field)]
    present = len(required) - len(missing)
    if present == len(required) and relevant:
        status = "BOUND"
    elif present and relevant:
        status = "PARTIALLY_BOUND"
    else:
        status = "UNBOUND_INSUFFICIENT"
    record = {
        "schema": "evidence-binding.v1",
        "binding_id": f"historical-reconciliation-{uuid4().hex}",
        "record_type": "historical_reconciliation",
        "binding_status": status,
        "subject": {
            "task_ref": fields.get("task_ref"),
            "implementation_revision_ref": fields.get("implementation_revision_ref"),
            "implementation_context_id": fields.get("implementation_context_id"),
        },
        "review": {
            "request_ref": None,
            "reviewer_ref": fields.get("reviewer_ref"),
            "reviewer_context_id": fields.get("reviewer_context_id"),
            "independence_required": bool(fields.get("independence_required", False)),
            "core_invocation_id": fields.get("core_invocation_id"),
            "provider": {"provider_ref": fields.get("provider_ref"), "model": fields.get("model"), "provider_request_id": fields.get("provider_request_id"), "provider_invocation_id": fields.get("provider_invocation_id")},
        },
        "evidence": {"raw": None, "review_result": None, "review_cycle": None, "acceptance": None},
        "lifecycle": {"retention_basis": "lifecycle-bound", "policy_ref": None, "state": "ACTIVE", "eligible_at": None, "eligibility_ref": None, "eligibility_evaluated_by": None, "deletion_authorization_ref": None, "deletion_authorized_by": None, "deletion_receipt": None},
        "historical_reconciliation": {"status": status, "missing_fields": missing, "limitations": [f"historical source: {source_ref}", *(limitations or [])], "reconciled_at": _now()},
    }
    record["binding_digest"] = digest_for(record)
    return validate_binding(record)


class EvidenceBindingStore:
    """Persist Core-owned bindings and enforce two-stage raw-evidence deletion."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def persist(self, binding: Mapping[str, Any]) -> dict[str, Any]:
        value = validate_binding(binding)
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value["binding_id"]):
            raise EvidenceBindingError("binding_id must be path-safe")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.root / f"{value['binding_id']}.json"
        if path.exists():
            raise EvidenceBindingError("evidence binding already exists; refusing overwrite")
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=self.root)
        try:
            with open(fd, "w", encoding="utf-8", closefd=True) as stream:
                json.dump(value, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
            Path(temporary).replace(path)
        finally:
            temporary_path = Path(temporary)
            if temporary_path.exists():
                temporary_path.unlink()
        return value

    def load(self, binding_id: str) -> dict[str, Any]:
        path = self.root / f"{binding_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceBindingError("evidence binding is unreadable") from exc
        return validate_binding(value)

    def evaluate_eligibility(self, binding_id: str, *, lifecycle_complete: bool, evidence_still_required: bool, evaluated_by: str, eligibility_ref: str) -> dict[str, Any]:
        value = self.load(binding_id)
        if value["lifecycle"]["state"] != "ACTIVE":
            raise EvidenceBindingError("only active evidence can be evaluated for disposition")
        if not lifecycle_complete or evidence_still_required:
            raise EvidenceBindingError("evidence is not eligible for disposition")
        if not evaluated_by.strip() or not eligibility_ref.strip():
            raise EvidenceBindingError("eligibility evaluation requires authority references")
        value["binding_status"] = "ELIGIBLE_FOR_DISPOSITION"
        value["lifecycle"].update({"state": "ELIGIBLE_FOR_DISPOSITION", "eligible_at": _now(), "eligibility_ref": eligibility_ref, "eligibility_evaluated_by": evaluated_by})
        value["binding_digest"] = digest_for({key: item for key, item in value.items() if key != "binding_digest"})
        return self._replace(value)

    def authorize_deletion(self, binding_id: str, *, authority_ref: str, authorized_by: str = "") -> dict[str, Any]:
        value = self.load(binding_id)
        if value["lifecycle"]["state"] != "ELIGIBLE_FOR_DISPOSITION":
            raise EvidenceBindingError("deletion requires prior eligibility")
        if not authority_ref.strip() or not authorized_by.strip():
            raise EvidenceBindingError("explicit deletion authority and authorizer are required")
        value["binding_status"] = "DELETION_AUTHORIZED"
        value["lifecycle"].update({"state": "DELETION_AUTHORIZED", "deletion_authorization_ref": authority_ref, "deletion_authorized_by": authorized_by})
        value["binding_digest"] = digest_for({key: item for key, item in value.items() if key != "binding_digest"})
        return self._replace(value)

    def delete_raw_evidence(self, binding_id: str, *, evidence_root: str | Path, authorized_by: str) -> dict[str, Any]:
        value = self.load(binding_id)
        lifecycle = value["lifecycle"]
        if lifecycle["state"] != "DELETION_AUTHORIZED":
            raise EvidenceBindingError("raw evidence deletion requires explicit authorization")
        raw = value["evidence"]["raw"]
        if raw is None:
            raise EvidenceBindingError("raw evidence is required for deletion")
        root = Path(evidence_root).expanduser().resolve()
        target = (root / raw["ref"]).resolve()
        if root not in target.parents:
            raise EvidenceBindingError("raw evidence path escapes evidence root")
        if not target.is_file():
            raise EvidenceBindingError("raw evidence is not present")
        actual = digest_for(json.loads(target.read_text(encoding="utf-8"))) if target.suffix == ".json" else digest_for(target.read_text(encoding="utf-8"))
        if actual != raw["digest"]:
            raise EvidenceBindingError("raw evidence digest does not match binding")
        if not authorized_by.strip():
            raise EvidenceBindingError("deletion actor is required")
        if authorized_by != lifecycle["deletion_authorized_by"]:
            raise EvidenceBindingError("deletion actor does not match explicit authorization")
        receipt = {"receipt_id": f"deletion-receipt-{uuid4().hex}", "target_ref": raw["ref"], "target_digest": raw["digest"], "authorized_by": authorized_by, "authorization_ref": lifecycle["deletion_authorization_ref"], "deleted_at": _now()}
        updated = dict(value)
        updated["binding_status"] = "DELETED"
        updated["lifecycle"] = dict(value["lifecycle"])
        updated["lifecycle"].update({"state": "DELETED", "deletion_receipt": receipt})
        updated["binding_digest"] = digest_for({key: item for key, item in updated.items() if key != "binding_digest"})
        validate_binding(updated)
        original = target.read_bytes()
        target.unlink()
        try:
            return self._replace(updated)
        except Exception:
            target.write_bytes(original)
            raise

    def _replace(self, value: Mapping[str, Any]) -> dict[str, Any]:
        path = self.root / f"{value['binding_id']}.json"
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=self.root)
        try:
            with open(fd, "w", encoding="utf-8", closefd=True) as stream:
                json.dump(value, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
            Path(temporary).replace(path)
        finally:
            temporary_path = Path(temporary)
            if temporary_path.exists():
                temporary_path.unlink()
        return validate_binding(value)
