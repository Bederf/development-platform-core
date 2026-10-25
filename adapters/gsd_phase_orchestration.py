"""Phase-level one-shot orchestration for bounded GSD execution.

The phase is the unit of execution.  A validated phase authorization admits a
dependency graph once; ordinary tasks and checks inherit that authority until
the phase boundary, where one risk-derived review request and one prepared
phase acceptance decision are produced.  This module never grants acceptance,
creates authority, or advances into another phase.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

from .founder_acceptance_session import FounderAcceptanceSession, FounderAcceptanceSessionError
from .gsd_acceptance_boundary import AcceptanceBoundary, AcceptanceBoundaryError, prepare_phase_acceptance_boundary
from .independent_review import IndependentReviewAdapter


class PhaseOrchestrationError(ValueError):
    """Raised when phase execution cannot safely proceed."""


@dataclass(frozen=True)
class PhaseTask:
    """A bounded task in the admitted phase DAG."""

    task_id: str
    depends_on: tuple[str, ...]
    execute: Callable[[], Mapping[str, Any]]


@dataclass(frozen=True)
class PhaseCheck:
    """A deterministic verification check at the phase boundary."""

    check_id: str
    execute: Callable[[], Mapping[str, Any]]


def _digest(value: Mapping[str, Any], field: str = "evidence_digest") -> str:
    payload = dict(value)
    payload.pop(field, None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise PhaseOrchestrationError("refusing to overwrite existing phase evidence")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _topological_order(tasks: Sequence[PhaseTask]) -> list[PhaseTask]:
    by_id: dict[str, PhaseTask] = {}
    for task in tasks:
        if not task.task_id.strip():
            raise PhaseOrchestrationError("task_id is required")
        if task.task_id in by_id:
            raise PhaseOrchestrationError(f"duplicate phase task: {task.task_id}")
        by_id[task.task_id] = task
    for task in tasks:
        missing = set(task.depends_on) - set(by_id)
        if missing:
            raise PhaseOrchestrationError(f"task {task.task_id} has missing dependencies: {sorted(missing)}")
        if task.task_id in task.depends_on:
            raise PhaseOrchestrationError(f"task {task.task_id} depends on itself")

    remaining = {task.task_id: set(task.depends_on) for task in tasks}
    order: list[PhaseTask] = []
    while remaining:
        ready = sorted(task_id for task_id, dependencies in remaining.items() if not dependencies)
        if not ready:
            raise PhaseOrchestrationError("phase task graph contains a cycle")
        for task_id in ready:
            order.append(by_id[task_id])
            del remaining[task_id]
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return order


class PhaseOrchestrationController:
    """Execute one admitted phase through its review and acceptance boundary."""

    def __init__(self, session_path: str | Path, *, phase_id: str) -> None:
        if not phase_id.strip():
            raise PhaseOrchestrationError("phase_id is required")
        self.session = FounderAcceptanceSession(session_path)
        self.phase_id = phase_id

    def run(
        self,
        *,
        authorization: Mapping[str, Any],
        tasks: Sequence[PhaseTask],
        checks: Sequence[PhaseCheck],
        evidence_path: str | Path,
        review_required: bool,
        review_provider_ref: str,
        run_id: str | None = None,
        review_executor: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        session = self._validate_authorization(authorization)
        ordered = _topological_order(tasks)
        if not ordered:
            raise PhaseOrchestrationError("at least one phase task is required")
        if not checks:
            raise PhaseOrchestrationError("at least one phase verification check is required")
        if review_required and not review_provider_ref.strip():
            raise PhaseOrchestrationError("review provider reference is required by phase risk")

        run: dict[str, Any] = {
            "schema": "gsd-phase-run.v1",
            "run_id": run_id or f"{self.phase_id.lower()}-phase-{uuid4().hex}",
            "phase_id": self.phase_id,
            "session_id": session["session_id"],
            "session_digest": session["digest"],
            "authorization_digest": authorization["confirmation"]["digest"],
            "started_at": datetime.now(UTC).isoformat(),
            "review_policy": {
                "required": review_required,
                "provider_ref": review_provider_ref if review_required else "not-required-by-risk-policy",
                "source": "validated phase risk policy",
            },
            "task_results": [],
            "check_results": [],
            "status": "RUNNING",
            "acceptance": "NOT_GRANTED",
            "phase_boundary": "NOT_REACHED",
        }

        for task in ordered:
            try:
                result = dict(task.execute())
                passed = result.get("status") == "SUCCEEDED"
            except Exception as exc:  # bounded task failures are recorded and stop the phase
                result = {"status": "FAILED", "reason": type(exc).__name__}
                passed = False
            result["task_id"] = task.task_id
            result["depends_on"] = list(task.depends_on)
            run["task_results"].append(result)
            if not passed:
                run["status"] = "BLOCKED"
                run["stop_reason"] = f"phase task failed: {task.task_id}"
                return self._persist(run, evidence_path)

        for check in checks:
            if not check.check_id.strip():
                raise PhaseOrchestrationError("check_id is required")
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
                run["stop_reason"] = f"phase verification check failed: {check.check_id}"
                return self._persist(run, evidence_path)

        run["phase_boundary"] = "REACHED"
        if review_required:
            run["review_request"] = IndependentReviewAdapter.make_request(
                task_ref=self.phase_id,
                revision_ref=run["run_id"],
                package_ref=str(evidence_path),
                evidence_refs=[str(evidence_path)],
                reviewer_ref=review_provider_ref,
                request_id=f"review-request-{run['run_id']}",
            )
            if review_executor is None:
                run["status"] = "REVIEW_PENDING"
                run["stop_reason"] = "phase implementation complete; independent review runtime is not configured"
            else:
                try:
                    review = review_executor(run["review_request"])
                    if not isinstance(review, Mapping):
                        raise PhaseOrchestrationError("independent review runtime returned a non-object")
                    review_result = review.get("review_result")
                    review_cycle = review.get("review_cycle")
                    if not isinstance(review_result, Mapping) or not isinstance(review_cycle, Mapping):
                        raise PhaseOrchestrationError("independent review runtime returned incomplete evidence")
                    run["review_result"] = dict(review_result)
                    run["review_cycle"] = dict(review_cycle)
                    disposition = str(review_result.get("disposition", ""))
                    if disposition in {"PASS", "PASS_WITH_ADVISORIES"}:
                        run["status"] = "ACCEPTANCE_PENDING"
                        run["stop_reason"] = "independent review completed; separate phase acceptance decision is required"
                    else:
                        run["status"] = "BLOCKED"
                        run["stop_reason"] = f"independent review completed with disposition: {disposition or 'INVALID'}"
                except Exception as exc:
                    run["status"] = "BLOCKED"
                    run["stop_reason"] = f"independent review execution failed: {type(exc).__name__}"
        else:
            run["status"] = "ACCEPTANCE_PENDING"
            run["stop_reason"] = "phase implementation complete; phase acceptance preparation is available"
        return self._persist(run, evidence_path)

    def prepare_phase_acceptance(
        self,
        *,
        run: Mapping[str, Any],
        acceptance_evidence_path: str | Path,
        review_result: Mapping[str, Any] | None = None,
        review_cycle: Mapping[str, Any] | None = None,
    ) -> AcceptanceBoundary:
        if run.get("phase_id") != self.phase_id:
            raise PhaseOrchestrationError("run is bound to a different phase")
        if run.get("status") not in {"REVIEW_PENDING", "ACCEPTANCE_PENDING"}:
            raise PhaseOrchestrationError("phase has not reached its acceptance boundary")
        policy = run.get("review_policy")
        if not isinstance(policy, Mapping):
            raise PhaseOrchestrationError("phase review policy is missing")
        review_required = policy.get("required") is True
        provider_ref = str(policy.get("provider_ref", ""))
        try:
            boundary = prepare_phase_acceptance_boundary(
                phase_id=self.phase_id,
                session_id=str(run["session_id"]),
                session_digest=str(run["session_digest"]),
                run_id=str(run["run_id"]),
                run_evidence_digest=str(run["evidence_digest"]),
                review_required=review_required,
                review_provider_ref=provider_ref,
                technical_verification_passed=True,
                policy_basis="validated phase risk policy",
                review_result=review_result,
                review_cycle=review_cycle,
                evidence_refs=[str(acceptance_evidence_path), str(run.get("evidence_ref", ""))],
            )
        except AcceptanceBoundaryError as exc:
            raise PhaseOrchestrationError(str(exc)) from exc
        if boundary.prepared_acceptance is not None:
            record = dict(boundary.prepared_acceptance)
            _write_new(Path(acceptance_evidence_path), record)
        return boundary

    def _validate_authorization(self, authorization: Mapping[str, Any]) -> dict[str, Any]:
        try:
            session = self.session.load()
        except FounderAcceptanceSessionError as exc:
            raise PhaseOrchestrationError(f"session validation failed: {exc}") from exc
        prepared = authorization.get("prepared")
        confirmation = authorization.get("confirmation")
        if not isinstance(prepared, Mapping) or not isinstance(confirmation, Mapping):
            raise PhaseOrchestrationError("prepared phase authorization and confirmation are required")
        if prepared.get("phase_id") != self.phase_id or prepared.get("action") != "authorize-phase-execution":
            raise PhaseOrchestrationError("authorization is not for this phase")
        if prepared.get("session_id") != session["session_id"] or prepared.get("session_digest") != session["digest"]:
            raise PhaseOrchestrationError("authorization is not bound to the active session")
        if confirmation.get("response") != "yes" or confirmation.get("confirmed_by") != session["authority_subject"]:
            raise PhaseOrchestrationError("phase authorization confirmation is not attributable")
        if confirmation.get("session_digest") != session["digest"] or confirmation.get("prepared_digest") != prepared.get("prepared_digest"):
            raise PhaseOrchestrationError("phase authorization confirmation digest does not match prepared decision")
        return session

    @staticmethod
    def _persist(run: dict[str, Any], evidence_path: str | Path) -> dict[str, Any]:
        run["completed_at"] = datetime.now(UTC).isoformat()
        run["evidence_ref"] = str(evidence_path)
        run["evidence_digest"] = _digest(run)
        _write_new(Path(evidence_path), run)
        return run
