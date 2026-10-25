from __future__ import annotations

import pytest

from adapters.gsd_execution_journal import JournalStore
from adapters.gsd_execution_outcomes import DispatchOutcomeController, OutcomeError
from adapters.gsd_execution_state import AttemptState


INPUT_1 = "sha256:" + "1" * 64
INPUT_2 = "sha256:" + "2" * 64


def controller(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    return journal, DispatchOutcomeController(journal)


def test_intent_is_idempotent_and_does_not_dispatch(tmp_path):
    journal, outcomes = controller(tmp_path)
    first = outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    duplicate = outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    assert first.decision == "committed"
    assert duplicate.decision == "duplicate"
    assert [event.event_type for event in journal.events()] == ["OUTCOME", "DISPATCH_INTENT"]
    journal.close()


def test_intent_requires_canonical_operation_identity_and_rejects_duplicate_attempt(tmp_path):
    journal, outcomes = controller(tmp_path)
    outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    with pytest.raises(OutcomeError, match="different attempt"):
        outcomes.record_intent("op-1", attempt_id="a2", input_digest=INPUT_1)
    with pytest.raises(OutcomeError, match="input digest differs"):
        outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_2)
    assert len(journal.events()) == 2
    journal.close()


def test_crash_after_intent_commit_does_not_blindly_redispatch(tmp_path):
    journal, outcomes = controller(tmp_path)
    with pytest.raises(OutcomeError, match="could not be committed"):
        outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1, fault="after_commit")
    recovered = outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    assert recovered.decision == "duplicate"
    assert [event.event_type for event in journal.events()] == ["OUTCOME", "DISPATCH_INTENT"]
    journal.close()


def test_observations_are_journal_ordered_and_late_evidence_is_preserved(tmp_path):
    journal, outcomes = controller(tmp_path)
    outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    first = outcomes.record_observation(
        "op-1", attempt_id="a1", outcome=AttemptState.TIMED_OUT, observation_digest="timeout"
    )
    late = outcomes.record_observation(
        "op-1", attempt_id="a1", outcome=AttemptState.SUCCEEDED, observation_digest="success"
    )
    assert first.classification == "committed"
    assert late.classification == "late"
    assert [event.event_type for event in journal.events()] == [
        "OUTCOME", "DISPATCH_INTENT", "DISPATCH_OBSERVED", "DISPATCH_OBSERVED"
    ]
    journal.close()


@pytest.mark.parametrize(
    ("first", "late"),
    [
        (AttemptState.CANCELLED, AttemptState.SUCCEEDED),
        (AttemptState.FAILED, AttemptState.SUCCEEDED),
        (AttemptState.SUCCEEDED, AttemptState.CANCELLED),
    ],
)
def test_cancellation_and_failure_races_follow_journal_commit_order(tmp_path, first, late):
    journal, outcomes = controller(tmp_path)
    outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    committed = outcomes.record_observation(
        "op-1", attempt_id="a1", outcome=first, observation_digest="first"
    )
    later = outcomes.record_observation(
        "op-1", attempt_id="a1", outcome=late, observation_digest="late"
    )
    assert committed.classification == "committed"
    assert later.classification == "late"
    assert [event.payload.get("outcome") for event in journal.events() if event.event_type == "DISPATCH_OBSERVED"] == [
        first.value, late.value
    ]
    journal.close()


def test_duplicate_observation_is_idempotent(tmp_path):
    journal, outcomes = controller(tmp_path)
    outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    first = outcomes.record_observation(
        "op-1", attempt_id="a1", outcome=AttemptState.SUCCEEDED, observation_digest="success"
    )
    duplicate = outcomes.record_observation(
        "op-1", attempt_id="a1", outcome=AttemptState.SUCCEEDED, observation_digest="success"
    )
    assert first.sequence == duplicate.sequence
    assert duplicate.classification == "duplicate"
    assert len(journal.events()) == 3
    journal.close()


def test_unknown_is_explicit_and_blocks_unreconciled_observation(tmp_path):
    journal, outcomes = controller(tmp_path)
    outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    unknown = outcomes.record_observation(
        "op-1", attempt_id="a1", outcome=AttemptState.UNKNOWN, observation_digest="unknown"
    )
    assert unknown.classification == "committed"
    with pytest.raises(OutcomeError, match="requires explicit reconciliation"):
        outcomes.record_observation(
            "op-1", attempt_id="a1", outcome=AttemptState.SUCCEEDED, observation_digest="success"
        )
    assert len(journal.events()) == 3
    journal.close()


def test_unsupported_observation_and_wrong_attempt_fail_closed(tmp_path):
    journal, outcomes = controller(tmp_path)
    outcomes.record_intent("op-1", attempt_id="a1", input_digest=INPUT_1)
    with pytest.raises(OutcomeError, match="unsupported"):
        outcomes.record_observation(
            "op-1", attempt_id="a1", outcome=AttemptState.RUNNING, observation_digest="running"
        )
    with pytest.raises(OutcomeError, match="different attempt"):
        outcomes.record_observation(
            "op-1", attempt_id="a2", outcome=AttemptState.SUCCEEDED, observation_digest="success"
        )
    assert len(journal.events()) == 2
    journal.close()
