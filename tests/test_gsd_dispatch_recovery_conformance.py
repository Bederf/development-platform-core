from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from adapters.agent_runtime import AgentExecutionIdentity
from adapters.gsd_execution_admission import AdmissionDecision
from adapters.gsd_execution_identity import OperationIdentity
from adapters.gsd_execution_journal import JournalStore
from adapters.gsd_execution_outcomes import DispatchOutcomeController, OutcomeError
from adapters.gsd_execution_reconciliation import UnknownOutcomeController
from adapters.gsd_execution_state import AttemptState
from adapters.gsd_execution_workspace import WorkspaceIdentity, WorkspaceReservationController
from adapters.gsd_executor_adapter import build_executor_dispatch_request
from adapters.gsd_fake_executor import FakeExecutor


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def controller_request(operation: OperationIdentity, *, attempt_id: str = "attempt-1"):
    return build_executor_dispatch_request(
        identity=AgentExecutionIdentity("dpc", "task-1", "run-1", "execution-1", attempt_id),
        operation=operation,
        admission=AdmissionDecision("op-1", "task-1", attempt_id, "slot-1", "graph-1", 7, "slot:task-1"),
        agent="codex",
        mode="read_only",
        startup_context={"schema": "agent-startup-context.v1", "current_objective": "qualify recovery"},
        objective="qualify recovery",
        request_id=f"{operation.operation_id}-{attempt_id}",
    )


def workspace(journal: JournalStore, root: Path) -> WorkspaceReservationController:
    return WorkspaceReservationController(journal, state_root=str(root / "state"), controller_epoch=1)


def identity(root: Path, *, attempt_id: str = "attempt-1") -> WorkspaceIdentity:
    return WorkspaceIdentity(
        state_root=str(root / "state"), run_id="run-1", execution_id="execution-1",
        task_id="task-1", attempt_id=attempt_id, workspace_id=f"workspace-{attempt_id}",
        workspace_root=str(root / f"workspace-{attempt_id}"), controller_epoch=1,
    )


def manifest(owner: WorkspaceIdentity, *, operation_id: str = "op-1") -> dict:
    return {
        "operation_id": operation_id,
        "identity": owner.as_payload(),
        "artifacts": [],
    }


def test_successful_fake_dispatch_is_journal_and_workspace_bound(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "journal")
    operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
    request = controller_request(operation)
    reservation = workspace(journal, tmp_path).reserve(identity(tmp_path), operation_id="op-1")
    outcomes = DispatchOutcomeController(journal)
    outcomes.record_intent("op-1", attempt_id="attempt-1", input_digest=operation.input_digest)
    fake = FakeExecutor()
    result = fake.execute(request)
    observed = outcomes.record_observation(
        "op-1", attempt_id="attempt-1", outcome=AttemptState.SUCCEEDED,
        observation_digest=digest(result.response),
    )
    released = workspace(journal, tmp_path).release(
        "op-1", reconciliation_digest=digest({"outcome": observed.outcome.value}),
        evidence_manifest=manifest(identity(tmp_path)), cleanup_succeeded=True,
    )
    assert reservation.identity.attempt_id == "attempt-1"
    assert observed.outcome is AttemptState.SUCCEEDED
    assert released.ownership_state == "RELEASED"


def test_lost_acknowledgement_quarantines_and_requires_reconciliation(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "journal")
    operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
    workspace(journal, tmp_path).reserve(identity(tmp_path), operation_id="op-1")
    outcomes = DispatchOutcomeController(journal)
    outcomes.record_intent("op-1", attempt_id="attempt-1", input_digest=operation.input_digest)
    unknown = outcomes.record_observation(
        "op-1", attempt_id="attempt-1", outcome=AttemptState.UNKNOWN,
        observation_digest=digest({"ack": "lost"}),
    )
    recovered = workspace(journal, tmp_path).recover_uncertain()
    assert unknown.outcome is AttemptState.UNKNOWN
    assert recovered[0].ownership_state == "QUARANTINED"
    assert recovered[0].quarantine_trigger == "unknown_outcome"
    reconciliation = UnknownOutcomeController(journal).reconcile_unknown(
        "op-1", attempt_id="attempt-1", prior_observation_digest=unknown.observation_digest,
        decision="RETRY_SAFE", evidence_digest=digest({"operator": "reconciled"}),
    )
    assert reconciliation.decision == "RETRY_SAFE"


def test_late_result_after_unknown_fails_closed_until_reconciliation(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "journal")
    operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
    outcomes = DispatchOutcomeController(journal)
    outcomes.record_intent("op-1", attempt_id="attempt-1", input_digest=operation.input_digest)
    outcomes.record_observation(
        "op-1", attempt_id="attempt-1", outcome=AttemptState.UNKNOWN,
        observation_digest=digest({"ack": "lost"}),
    )
    with pytest.raises(OutcomeError, match="unknown outcome requires explicit reconciliation"):
        outcomes.record_observation(
            "op-1", attempt_id="attempt-1", outcome=AttemptState.SUCCEEDED,
            observation_digest=digest({"late": "success"}),
        )


def test_cleanup_failure_preserves_evidence_and_blocks_workspace(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "journal")
    controller = workspace(journal, tmp_path)
    controller.reserve(identity(tmp_path), operation_id="op-1")
    released = controller.release(
        "op-1", reconciliation_digest=digest({"reconciled": True}),
        evidence_manifest=manifest(identity(tmp_path)),
        cleanup_succeeded=False,
    )
    assert released.ownership_state == "QUARANTINED"
    assert released.task_blocked is True
    assert released.evidence_manifest_digest is not None
