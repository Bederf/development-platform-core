from __future__ import annotations

import pytest

from adapters.gsd_execution_journal import JournalStore
from adapters.gsd_execution_outcomes import DispatchOutcomeController
from adapters.gsd_execution_reconciliation import ReconciliationError, UnknownOutcomeController
from adapters.gsd_execution_state import AttemptState


INPUT_1 = "sha256:" + "1" * 64


def setup(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    outcomes = DispatchOutcomeController(journal)
    outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    outcomes.record_observation(
        "op-1", attempt_id="a1", outcome=AttemptState.UNKNOWN, observation_digest="unknown-1"
    )
    return journal, UnknownOutcomeController(journal)


def test_unknown_requires_exact_operation_and_observation_identity(tmp_path):
    journal, controller = setup(tmp_path)
    with pytest.raises(ReconciliationError, match="does not match"):
        controller.reconcile_unknown(
            "op-1", attempt_id="a1", prior_observation_digest="wrong",
            decision="RETRY_SAFE", evidence_digest="evidence-1"
        )
    with pytest.raises(ReconciliationError, match="missing"):
        controller.reconcile_unknown(
            "op-2", attempt_id="a1", prior_observation_digest="unknown-1",
            decision="RETRY_SAFE", evidence_digest="evidence-1"
        )
    assert len(journal.events()) == 3
    journal.close()


def test_unknown_reconciliation_is_durable_and_idempotent(tmp_path):
    journal, controller = setup(tmp_path)
    first = controller.reconcile_unknown(
        "op-1", attempt_id="a1", prior_observation_digest="unknown-1",
        decision="RETRY_SAFE", evidence_digest="evidence-1"
    )
    duplicate = controller.reconcile_unknown(
        "op-1", attempt_id="a1", prior_observation_digest="unknown-1",
        decision="RETRY_SAFE", evidence_digest="evidence-1"
    )
    assert first == duplicate
    assert len(journal.events()) == 4
    journal.close()


def test_confirmed_terminal_reconciliation_requires_and_records_outcome(tmp_path):
    journal, controller = setup(tmp_path)
    with pytest.raises(ReconciliationError, match="terminal outcome"):
        controller.reconcile_unknown(
            "op-1", attempt_id="a1", prior_observation_digest="unknown-1",
            decision="CONFIRMED_TERMINAL", evidence_digest="evidence-1"
        )
    decision = controller.reconcile_unknown(
        "op-1", attempt_id="a1", prior_observation_digest="unknown-1",
        decision="CONFIRMED_TERMINAL", evidence_digest="evidence-1",
        confirmed_outcome=AttemptState.FAILED,
    )
    assert decision.decision == "CONFIRMED_TERMINAL"
    assert journal.events()[-1].payload["confirmed_outcome"] == "FAILED"
    assert journal.replay().reconciled_outcomes["a1"] is AttemptState.FAILED
    journal.close()


def test_unsafe_retry_is_blocked_until_explicit_safe_reconciliation(tmp_path):
    journal, controller = setup(tmp_path)
    with pytest.raises(ReconciliationError, match="RETRY_SAFE"):
        controller.authorize_retry(
            "op-1", prior_attempt_id="a1", new_attempt_id="a2",
            task_retry_safe=True, retry_reason="replay"
        )
    controller.reconcile_unknown(
        "op-1", attempt_id="a1", prior_observation_digest="unknown-1",
        decision="NOT_RETRYABLE", evidence_digest="evidence-1"
    )
    with pytest.raises(ReconciliationError, match="RETRY_SAFE"):
        controller.authorize_retry(
            "op-1", prior_attempt_id="a1", new_attempt_id="a2",
            task_retry_safe=True, retry_reason="replay"
        )
    journal.close()


def test_safe_retry_has_new_identity_and_preserves_prior_evidence(tmp_path):
    journal, controller = setup(tmp_path)
    controller.reconcile_unknown(
        "op-1", attempt_id="a1", prior_observation_digest="unknown-1",
        decision="RETRY_SAFE", evidence_digest="evidence-1"
    )
    lineage = controller.authorize_retry(
        "op-1", prior_attempt_id="a1", new_attempt_id="a2",
        task_retry_safe=True, retry_reason="provider-replay-qualified"
    )
    assert lineage.new_attempt_id == "a2"
    assert lineage.prior_attempt_id == "a1"
    assert lineage.prior_observation_digest == "unknown-1"
    assert lineage.reconciliation_evidence_digest == "evidence-1"
    replay = journal.replay()
    assert replay.attempt_states["a2"] is AttemptState.CREATED
    assert journal.events()[-1].payload["projected_state"] == "CREATED"
    journal.close()


def test_retry_requires_distinct_attempt_and_reason(tmp_path):
    journal, controller = setup(tmp_path)
    controller.reconcile_unknown(
        "op-1", attempt_id="a1", prior_observation_digest="unknown-1",
        decision="RETRY_SAFE", evidence_digest="evidence-1"
    )
    with pytest.raises(ReconciliationError, match="distinct attempt"):
        controller.authorize_retry(
            "op-1", prior_attempt_id="a1", new_attempt_id="a1",
            task_retry_safe=True, retry_reason="replay"
        )
    with pytest.raises(ReconciliationError, match="reason"):
        controller.authorize_retry(
            "op-1", prior_attempt_id="a1", new_attempt_id="a2",
            task_retry_safe=True, retry_reason=""
        )
    journal.close()
