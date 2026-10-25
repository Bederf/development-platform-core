from __future__ import annotations

import ast
from pathlib import Path
from threading import Thread

import pytest

from adapters.gsd_execution_journal import JournalEvent, JournalStore
from adapters.gsd_execution_workspace import (
    WorkspaceIdentity,
    WorkspaceOwnershipError,
    WorkspaceReservationController,
)


def identity(root: Path, *, workspace_id: str = "workspace-1", workspace_root: Path | None = None, epoch: int = 1):
    return WorkspaceIdentity(
        state_root=str(root),
        run_id="run-1",
        execution_id="execution-1",
        task_id="task-1",
        attempt_id="attempt-1",
        workspace_id=workspace_id,
        workspace_root=str(workspace_root or root / "workspaces" / workspace_id),
        controller_epoch=epoch,
    )


def controller(tmp_path: Path, *, epoch: int = 1):
    state_root = tmp_path / "controller-state"
    return WorkspaceReservationController(
        JournalStore(tmp_path / "journal.sqlite"),
        state_root=str(state_root),
        controller_epoch=epoch,
    ), state_root


def test_identity_binds_controller_state_and_mutating_attempt():
    value = identity(Path("/tmp/controller-state"))
    assert value.policy == "exclusive"
    assert value.state_root == "/tmp/controller-state"
    assert value.workspace_root == "/tmp/controller-state/workspaces/workspace-1"


def test_identity_rejects_legacy_state_root_and_relative_workspace():
    with pytest.raises(WorkspaceOwnershipError, match="legacy"):
        identity(Path("/tmp/.gsd-engine"))
    with pytest.raises(WorkspaceOwnershipError, match="absolute"):
        WorkspaceIdentity(
            state_root="/tmp/controller-state", run_id="r", execution_id="e",
            task_id="t", attempt_id="a", workspace_id="w",
            workspace_root="relative", controller_epoch=1,
        )


def test_reservation_is_journal_backed_idempotent_and_replayable(tmp_path):
    owner, state_root = controller(tmp_path)
    first = owner.reserve(identity(state_root), operation_id="admission:op-1")
    second = owner.reserve(identity(state_root), operation_id="admission:op-1")
    assert second == first
    assert owner.replay_reservations() == (first,)
    owner.journal.close()

    reopened = WorkspaceReservationController(
        JournalStore(tmp_path / "journal.sqlite"), state_root=str(state_root), controller_epoch=1
    )
    assert reopened.replay_reservations() == (first,)
    reopened.journal.close()


def test_same_operation_with_different_owner_is_conflict_without_mutation(tmp_path):
    owner, state_root = controller(tmp_path)
    owner.reserve(identity(state_root), operation_id="admission:op-1")
    with pytest.raises(WorkspaceOwnershipError, match="conflicting duplicate"):
        owner.reserve(identity(state_root, workspace_id="workspace-2"), operation_id="admission:op-1")
    assert len(owner.journal.events()) == 1
    owner.journal.close()


def test_active_workspace_id_and_root_collisions_are_rejected(tmp_path):
    owner, state_root = controller(tmp_path)
    owner.reserve(identity(state_root), operation_id="admission:op-1")
    with pytest.raises(WorkspaceOwnershipError, match="exclusively owned"):
        owner.reserve(identity(state_root, workspace_id="workspace-1", workspace_root=state_root / "other"), operation_id="admission:op-2")
    with pytest.raises(WorkspaceOwnershipError, match="quarantined"):
        owner.reserve(
            identity(
                state_root,
                workspace_id="workspace-2",
                workspace_root=state_root / "workspaces" / "workspace-1",
            ),
            operation_id="admission:op-3",
        )
    owner.journal.close()


def test_stale_owner_cannot_be_reused_by_new_epoch(tmp_path):
    first, state_root = controller(tmp_path, epoch=1)
    first.reserve(identity(state_root, epoch=1), operation_id="admission:op-1")
    first.journal.close()
    second = WorkspaceReservationController(
        JournalStore(tmp_path / "journal.sqlite"), state_root=str(state_root), controller_epoch=2
    )
    with pytest.raises(WorkspaceOwnershipError, match="stale"):
        second.reserve(identity(state_root, epoch=2), operation_id="admission:op-2")
    second.journal.close()


def test_explicit_quarantine_preserves_lineage_and_blocks_reuse(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-1")
    quarantined = owner.quarantine(
        "op-1", trigger="unknown_outcome", reason="attempt outcome is unresolved",
        evidence_digest="sha256:" + "1" * 64,
    )
    assert quarantined.ownership_state == "QUARANTINED"
    assert quarantined.task_blocked is True
    assert quarantined.sequence > reserved.sequence
    assert quarantined.identity == reserved.identity
    with pytest.raises(WorkspaceOwnershipError, match="quarantined"):
        owner.reserve(
            identity(state_root, workspace_id="workspace-2", workspace_root=state_root / "workspaces" / "workspace-1"),
            operation_id="op-2",
        )
    owner.journal.close()


def test_crash_and_unknown_recovery_quarantine_active_owner(tmp_path):
    owner, state_root = controller(tmp_path)
    crash = owner.reserve(identity(state_root, workspace_id="crash"), operation_id="op-crash")
    owner.journal.append(JournalEvent(
        "dispatch-intent:op-crash", "DISPATCH_INTENT", 1, "op-crash", {"attempt_id": "attempt-1"}
    ))
    unknown = owner.reserve(identity(state_root, workspace_id="unknown"), operation_id="op-unknown")
    owner.journal.append(JournalEvent(
        "dispatch-observed:op-unknown", "DISPATCH_OBSERVED", 1, "op-unknown",
        {"attempt_id": "attempt-1", "outcome": "UNKNOWN"},
    ))
    recovered = owner.recover_uncertain()
    by_operation = {item.operation_id: item for item in recovered}
    assert by_operation[crash.operation_id].quarantine_trigger == "crash"
    assert by_operation[unknown.operation_id].quarantine_trigger == "unknown_outcome"
    assert all(item.task_blocked for item in (by_operation[crash.operation_id], by_operation[unknown.operation_id]))
    owner.journal.close()


def test_contradictory_ownership_is_quarantined_with_evidence(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-contradiction")
    observed = owner.observe_ownership(
        "op-contradiction", observed_workspace_id="different",
        observed_workspace_root=str(state_root / "workspaces" / "different"),
        evidence_digest="sha256:" + "2" * 64,
    )
    assert observed.ownership_state == "QUARANTINED"
    assert observed.quarantine_trigger == "contradictory_ownership"
    assert observed.evidence_digest == "sha256:" + "2" * 64
    assert observed.identity == reserved.identity
    owner.journal.close()


def test_replay_rejects_quarantine_identity_mismatch(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-identity")
    payload = {
        "kind": "WORKSPACE_OWNERSHIP_QUARANTINED",
        "ownership_state": "QUARANTINED",
        "operation_id": "op-identity",
        "prior_reservation_sequence": reserved.sequence,
        "quarantine_trigger": "crash",
        "quarantine_reason": "crash evidence",
        "evidence_digest": "sha256:" + "1" * 64,
        "task_blocked": True,
        **{**reserved.identity.as_payload(), "attempt_id": "forged-attempt"},
    }
    owner.journal.append(JournalEvent("quarantine-identity", "OUTCOME", 1, "op-identity", payload))
    with pytest.raises(WorkspaceOwnershipError, match="does not match reservation"):
        owner.replay_reservations()
    owner.journal.close()


def test_replay_rejects_orphan_quarantine_evidence(tmp_path):
    owner, state_root = controller(tmp_path)
    payload = {
        "kind": "WORKSPACE_OWNERSHIP_QUARANTINED",
        "ownership_state": "QUARANTINED",
        "operation_id": "orphan-operation",
        "prior_reservation_sequence": 1,
        "quarantine_trigger": "crash",
        "quarantine_reason": "orphan evidence",
        "evidence_digest": "sha256:" + "2" * 64,
        "task_blocked": True,
    }
    owner.journal.append(JournalEvent("quarantine-orphan", "OUTCOME", 1, "orphan-operation", payload))
    with pytest.raises(WorkspaceOwnershipError, match="no workspace reservation"):
        owner.replay_reservations()
    owner.journal.close()


def test_replay_rejects_multiple_quarantine_records_for_one_operation(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-multiple")
    for event_id, trigger in (("quarantine-one", "crash"), ("quarantine-two", "unknown_outcome")):
        payload = {
            "kind": "WORKSPACE_OWNERSHIP_QUARANTINED",
            "ownership_state": "QUARANTINED",
            "operation_id": "op-multiple",
            "prior_reservation_sequence": reserved.sequence,
            "quarantine_trigger": trigger,
            "quarantine_reason": "conflicting evidence",
            "evidence_digest": "sha256:" + "3" * 64,
            "task_blocked": True,
            **reserved.identity.as_payload(),
        }
        owner.journal.append(JournalEvent(event_id, "OUTCOME", 1, "op-multiple", payload))
    with pytest.raises(WorkspaceOwnershipError, match="multiple quarantine"):
        owner.replay_reservations()
    owner.journal.close()


def evidence_manifest(reserved):
    return {
        "operation_id": reserved.operation_id,
        "identity": reserved.identity.as_payload(),
        "artifacts": [{"path": "evidence.json", "sha256": "a" * 64}],
    }


def test_release_preserves_evidence_before_releasing_workspace(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-release")
    released = owner.release(
        "op-release",
        reconciliation_digest="sha256:" + "4" * 64,
        evidence_manifest=evidence_manifest(reserved),
        cleanup_succeeded=True,
    )
    assert released.ownership_state == "RELEASED"
    assert released.task_blocked is False
    events = owner.journal.events()
    assert [event.payload["kind"] for event in events[-2:]] == [
        "WORKSPACE_EVIDENCE_PRESERVED", "WORKSPACE_RELEASED"
    ]
    assert owner.replay_reservations() == (released,)
    owner.journal.close()


def test_cleanup_failure_preserves_evidence_and_quarantines_workspace(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-cleanup-failure")
    failed = owner.release(
        "op-cleanup-failure",
        reconciliation_digest="sha256:" + "5" * 64,
        evidence_manifest=evidence_manifest(reserved),
        cleanup_succeeded=False,
    )
    assert failed.ownership_state == "QUARANTINED"
    assert failed.quarantine_trigger == "cleanup_failure"
    assert failed.task_blocked is True
    with pytest.raises(WorkspaceOwnershipError, match="quarantined"):
        owner.reserve(
            identity(state_root, workspace_id="workspace-2", workspace_root=state_root / "workspaces" / "workspace-1"),
            operation_id="op-cleanup-reuse",
        )
    assert owner.replay_reservations() == (failed,)
    owner.journal.close()


def test_release_requires_reconciliation_and_valid_evidence_manifest(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-release-validation")
    with pytest.raises(WorkspaceOwnershipError, match="reconciliation digest"):
        owner.release(
            "op-release-validation", reconciliation_digest="invalid",
            evidence_manifest=evidence_manifest(reserved), cleanup_succeeded=True,
        )
    invalid_manifest = evidence_manifest(reserved)
    invalid_manifest["identity"] = {**reserved.identity.as_payload(), "attempt_id": "forged"}
    with pytest.raises(WorkspaceOwnershipError, match="manifest identity"):
        owner.release(
            "op-release-validation", reconciliation_digest="sha256:" + "6" * 64,
            evidence_manifest=invalid_manifest, cleanup_succeeded=True,
        )
    assert len(owner.journal.events()) == 1
    owner.journal.close()


def test_released_workspace_rejects_conflicting_duplicate_evidence(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-release-duplicate")
    manifest = evidence_manifest(reserved)
    released = owner.release(
        "op-release-duplicate",
        reconciliation_digest="sha256:" + "7" * 64,
        evidence_manifest=manifest,
        cleanup_succeeded=True,
    )
    changed_manifest = {**manifest, "artifacts": [{"path": "different.json", "sha256": "b" * 64}]}
    with pytest.raises(WorkspaceOwnershipError, match="conflicting duplicate"):
        owner.release(
            "op-release-duplicate",
            reconciliation_digest="sha256:" + "8" * 64,
            evidence_manifest=changed_manifest,
            cleanup_succeeded=True,
        )
    assert owner.replay_reservations() == (released,)
    owner.journal.close()


def test_released_workspace_rejects_same_evidence_with_failed_cleanup(tmp_path):
    owner, state_root = controller(tmp_path)
    reserved = owner.reserve(identity(state_root), operation_id="op-release-outcome-conflict")
    manifest = evidence_manifest(reserved)
    owner.release(
        "op-release-outcome-conflict",
        reconciliation_digest="sha256:" + "9" * 64,
        evidence_manifest=manifest,
        cleanup_succeeded=True,
    )
    with pytest.raises(WorkspaceOwnershipError, match="conflicting duplicate"):
        owner.release(
            "op-release-outcome-conflict",
            reconciliation_digest="sha256:" + "9" * 64,
            evidence_manifest=manifest,
            cleanup_succeeded=False,
        )
    owner.journal.close()


def test_concurrent_controllers_commit_only_one_owner(tmp_path):
    state_root = tmp_path / "controller-state"
    journal_path = tmp_path / "journal.sqlite"
    results = []

    def reserve(index: int) -> None:
        owner = WorkspaceReservationController(
            JournalStore(journal_path), state_root=str(state_root), controller_epoch=1
        )
        value = identity(
            state_root,
            workspace_id=f"workspace-{index}",
            workspace_root=state_root / "workspaces" / "shared",
        )
        try:
            owner.reserve(value, operation_id=f"admission:op-{index}")
            results.append("committed")
        except WorkspaceOwnershipError:
            results.append("rejected")
        finally:
            owner.journal.close()

    threads = [Thread(target=reserve, args=(1,)), Thread(target=reserve, args=(2,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["committed", "rejected"]
    journal = JournalStore(journal_path)
    owners = [
        event
        for event in journal.events()
        if event.payload.get("kind") == "WORKSPACE_OWNERSHIP_RESERVED"
    ]
    assert len(owners) == 1
    journal.close()


def test_state_root_mismatch_is_rejected_before_journal_mutation(tmp_path):
    owner, state_root = controller(tmp_path)
    with pytest.raises(WorkspaceOwnershipError, match="outside controller state root"):
        owner.reserve(identity(tmp_path / "other-state"), operation_id="admission:op-1")
    assert owner.journal.events() == ()
    owner.journal.close()


def test_p5_module_has_no_provider_dispatch_or_filesystem_mutation_imports():
    tree = ast.parse(Path("adapters/gsd_execution_workspace.py").read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0])
    assert not {"subprocess", "socket", "requests", "httpx", "boto3"}.intersection(imports)
    source = Path("adapters/gsd_execution_workspace.py").read_text(encoding="utf-8").lower()
    assert "mkdir" not in source
    assert "unlink" not in source
    assert "rmtree" not in source
