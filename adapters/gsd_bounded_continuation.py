"""Bounded, fail-closed continuation for an authorized GSD task slice.

This controller deliberately stops at the independent-review boundary.  It
does not grant authority, invoke a provider, accept a deliverable, or advance
the phase.  It only correlates an already-authorized Founder session with
deterministic local work and content-bound run evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Literal
from uuid import uuid4

from .founder_acceptance_session import FounderAcceptanceSession, FounderAcceptanceSessionError
from .independent_review import IndependentReviewAdapter


class BoundedContinuationError(ValueError):
    """Raised when bounded continuation cannot safely proceed."""


TaskState = Literal["SUCCEEDED", "FAILED", "BLOCKED"]


@dataclass(frozen=True)
class BoundedTask:
    """A local task callback; callbacks must not perform provider dispatch."""

    task_id: str
    execute: Callable[[], Mapping[str, Any]]


@dataclass(frozen=True)
class DeterministicCheck:
    """A local deterministic check required before the review boundary."""

    check_id: str
    execute: Callable[[], Mapping[str, Any]]


def _digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("evidence_digest", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise BoundedContinuationError("refusing to overwrite existing run evidence")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


class BoundedContinuationController:
    """Run authorized local tasks and stop at the correct review boundary."""

    def __init__(self, session_path: str | Path, *, phase_id: str = "P050") -> None:
        self.session = FounderAcceptanceSession(session_path)
        self.phase_id = phase_id

    def run(
        self,
        *,
        authorization: Mapping[str, Any],
        tasks: Sequence[BoundedTask],
        checks: Sequence[DeterministicCheck],
        evidence_path: str | Path,
        review_required: bool,
        review_provider_ref: str,
        review_task_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        session = self._validate_authorization(authorization)
        if not tasks:
            raise BoundedContinuationError("at least one authorized task is required")
        if not checks:
            raise BoundedContinuationError("at least one deterministic check is required")
        if not review_provider_ref.strip():
            raise BoundedContinuationError("review provider reference is required")

        run: dict[str, Any] = {
            "schema": "gsd-bounded-continuation-run.v1",
            "run_id": run_id or f"{self.phase_id.lower()}-t002-{uuid4().hex}",
            "phase_id": self.phase_id,
            "session_id": session["session_id"],
            "session_digest": session["digest"],
            "authorization_digest": authorization["confirmation"]["digest"],
            "started_at": datetime.now(UTC).isoformat(),
            "review_policy": {
                "required": review_required,
                "provider_ref": review_provider_ref,
                "source": "validated phase risk policy",
            },
            "task_results": [],
            "check_results": [],
            "status": "RUNNING",
            "provider_invocation": "NOT_STARTED",
            "acceptance": "NOT_GRANTED",
        }

        for task in tasks:
            self._validate_id(task.task_id, "task_id")
            try:
                result = dict(task.execute())
                passed = result.get("status") == "SUCCEEDED"
            except Exception as exc:  # local task failures are recorded, never bypassed
                result = {"status": "FAILED", "reason": type(exc).__name__}
                passed = False
            result["task_id"] = task.task_id
            run["task_results"].append(result)
            if not passed:
                run["status"] = "BLOCKED"
                run["stop_reason"] = f"task failed: {task.task_id}"
                return self._persist(run, evidence_path)

        for check in checks:
            self._validate_id(check.check_id, "check_id")
            try:
                result = dict(check.execute())
                passed = result.get("status") == "PASSED"
            except Exception as exc:
                result = {"status": "FAILED", "reason": type(exc).__name__}
                passed = False
            result["check_id"] = check.check_id
            run["check_results"].append(result)
            if not passed:
                run["status"] = "BLOCKED"
                run["stop_reason"] = f"deterministic check failed: {check.check_id}"
                return self._persist(run, evidence_path)

        if review_required:
            request = IndependentReviewAdapter.make_request(
                task_ref=review_task_id or f"{self.phase_id}-T002",
                revision_ref=run["run_id"],
                package_ref=str(evidence_path),
                evidence_refs=[str(evidence_path)],
                reviewer_ref=review_provider_ref,
                request_id=f"review-request-{run['run_id']}",
            )
            run["review_request"] = request
            run["status"] = "REVIEW_PENDING"
            run["stop_reason"] = "bounded work complete; independent review required"
        else:
            run["status"] = "DETERMINISTIC_COMPLETE"
            run["stop_reason"] = "bounded work complete; no independent review required by phase policy"
        return self._persist(run, evidence_path)

    def _validate_authorization(self, authorization: Mapping[str, Any]) -> dict[str, Any]:
        try:
            session = self.session.load()
        except FounderAcceptanceSessionError as exc:
            raise BoundedContinuationError(f"session validation failed: {exc}") from exc
        prepared = authorization.get("prepared")
        confirmation = authorization.get("confirmation")
        if not isinstance(prepared, Mapping) or not isinstance(confirmation, Mapping):
            raise BoundedContinuationError("prepared authorization and confirmation are required")
        if prepared.get("phase_id") != self.phase_id or prepared.get("action") != "authorize-bounded-task":
            raise BoundedContinuationError("authorization is not for this bounded task")
        if prepared.get("session_id") != session["session_id"] or prepared.get("session_digest") != session["digest"]:
            raise BoundedContinuationError("authorization is not bound to the active session")
        if confirmation.get("response") != "yes" or confirmation.get("confirmed_by") != session["authority_subject"]:
            raise BoundedContinuationError("authorization confirmation is not attributable")
        if confirmation.get("session_digest") != session["digest"] or confirmation.get("prepared_digest") != prepared.get("prepared_digest"):
            raise BoundedContinuationError("authorization confirmation digest does not match prepared decision")
        return session

    @staticmethod
    def _validate_id(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise BoundedContinuationError(f"{name} is required")

    @staticmethod
    def _persist(run: dict[str, Any], evidence_path: str | Path) -> dict[str, Any]:
        run["completed_at"] = datetime.now(UTC).isoformat()
        run["evidence_digest"] = _digest(run)
        _write_new(Path(evidence_path), run)
        return run
