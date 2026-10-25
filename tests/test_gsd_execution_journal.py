import pytest

from adapters.gsd_execution_journal import JournalError, JournalEvent, JournalStore


def event(event_id, event_type, operation_id, payload, epoch=1):
    return JournalEvent(event_id, event_type, epoch, operation_id, payload)


def test_identical_event_insertion_is_idempotent(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    original = event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"})
    assert journal.append(original).sequence == 1
    assert journal.append(original).sequence == 1
    assert len(journal.events()) == 1
    assert journal.events()[0].sequence == 1
    journal.close()


def test_conflicting_event_insertion_is_rejected(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}))
    with pytest.raises(JournalError, match="conflicting"):
        journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "RUNNING"}))
    journal.close()


def test_unknown_event_type_is_rejected_on_append(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    with pytest.raises(JournalError, match="unknown journal event type"):
        journal.append(event("e1", "UNDECLARED_EVENT", "op-1", {}))
    assert journal.events() == ()
    journal.close()


def test_batch_append_is_atomic_and_sequences_events(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    batch = [
        event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}),
        event("e2", "DISPATCH_INTENT", "op-1", {"attempt_id": "a1"}),
    ]
    result = journal.append_batch(batch)
    assert [item.event_id for item in result] == ["e1", "e2"]
    assert [item.sequence for item in result] == [1, 2]
    assert [item.event_id for item in journal.events()] == ["e1", "e2"]
    assert [item.sequence for item in journal.events()] == [1, 2]
    journal.close()


def test_batch_append_rolls_back_all_events_before_commit(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    with pytest.raises(JournalError, match="before journal commit"):
        journal.append_batch([
            event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}),
            event("e2", "DISPATCH_INTENT", "op-1", {"attempt_id": "a1"}),
        ], fault="before_commit")
    journal.close()
    reopened = JournalStore(path)
    assert reopened.events() == ()
    reopened.close()


def test_dispatch_observation_resolves_incomplete_intent(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append_batch([
        event("e1", "DISPATCH_INTENT", "op-1", {"attempt_id": "a1"}),
        event("e2", "DISPATCH_OBSERVED", "op-1", {"attempt_id": "a1"}),
    ])
    assert journal.replay().incomplete_dispatch_intents == frozenset()
    journal.close()


def test_projection_rebuilds_and_incomplete_intent_is_not_success(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}))
    journal.append(event("e2", "DISPATCH_INTENT", "op-1", {"attempt_id": "a1"}))
    projection = journal.replay()
    assert projection.attempt_states["a1"].value == "CREATED"
    assert projection.incomplete_dispatch_intents == frozenset({"op-1"})
    assert [item.sequence for item in projection.events] == [1, 2]
    journal.close()
    reopened = JournalStore(path)
    assert reopened.replay() == projection
    assert reopened.replay().projection_digest == projection.projection_digest
    reopened.close()


def test_replay_projection_digest_changes_when_journal_content_changes(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}))
    first_digest = journal.replay().projection_digest
    journal.append(event("e2", "DISPATCH_INTENT", "op-1", {"attempt_id": "a1"}))
    assert journal.replay().projection_digest != first_digest
    journal.close()


def test_projection_rejects_invalid_attempt_transition(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}))
    journal.append(event("e2", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "SUCCEEDED"}))
    with pytest.raises(JournalError, match="invalid attempt transition"):
        journal.replay()
    journal.close()


def test_stale_epoch_cannot_append(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}, epoch=2))
    with pytest.raises(JournalError, match="stale controller epoch"):
        journal.append(event("e2", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "DISPATCHED"}, epoch=1))
    journal.close()


def test_crash_before_commit_leaves_no_event(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    with pytest.raises(JournalError, match="before journal commit"):
        journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}), fault="before_commit")
    journal.close()
    reopened = JournalStore(path)
    assert reopened.events() == ()
    reopened.close()


def test_crash_after_commit_replays_one_event_without_duplicate(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    with pytest.raises(JournalError, match="after journal commit"):
        journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}), fault="after_commit")
    journal.close()
    reopened = JournalStore(path)
    assert len(reopened.events()) == 1
    assert reopened.replay().attempt_states["a1"].value == "CREATED"
    reopened.close()


def test_crash_after_commit_batch_replays_once_and_preserves_unknown_intent(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    with pytest.raises(JournalError, match="after journal commit"):
        journal.append_batch([
            event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}),
            event("e2", "DISPATCH_INTENT", "op-1", {"attempt_id": "a1"}),
        ], fault="after_commit")
    journal.close()

    reopened = JournalStore(path)
    assert [item.sequence for item in reopened.events()] == [1, 2]
    projection = reopened.replay()
    assert projection.attempt_states["a1"].value == "CREATED"
    assert projection.incomplete_dispatch_intents == frozenset({"op-1"})
    reopened.close()


def test_controller_epoch_is_durable_across_reopen_and_fences_stale_append(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    journal.set_controller_epoch(3)
    journal.close()

    reopened = JournalStore(path)
    assert reopened.controller_epoch == 3
    with pytest.raises(JournalError, match="stale controller epoch"):
        reopened.append(
            event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}, epoch=2)
        )
    reopened.close()


def test_replay_rejects_sequence_gap(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}))
    journal.append(event("e2", "DISPATCH_INTENT", "op-1", {"attempt_id": "a1"}))
    journal._db.execute("DELETE FROM journal_events WHERE sequence=1")
    journal._db.commit()
    with pytest.raises(JournalError, match="sequence gap"):
        journal.replay()
    journal.close()


def test_replay_rejects_conflicting_payload_digest(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}))
    journal._db.execute("UPDATE journal_events SET payload=? WHERE event_id='e1'", ('{"attempt_id":"a1","state":"DISPATCHED"}',))
    journal._db.commit()
    with pytest.raises(JournalError, match="payload digest"):
        journal.replay()
    journal.close()


def test_replay_rejects_tampered_unknown_event_type(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append(event("e1", "DISPATCH_INTENT", "op-1", {"attempt_id": "a1"}))
    payload = "{}"
    digest = event("e1", "DISPATCH_INTENT", "op-1", {}).payload_digest
    journal._db.execute(
        "UPDATE journal_events SET event_type=?, payload=?, payload_digest=? WHERE event_id='e1'",
        ("UNDECLARED_EVENT", payload, digest),
    )
    journal._db.commit()
    with pytest.raises(JournalError, match="unknown journal event type during replay"):
        journal.replay()
    journal.close()


def test_replay_rejects_epoch_regression(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append(event("e1", "ATTEMPT_STATE", "op-1", {"attempt_id": "a1", "state": "CREATED"}, epoch=2))
    empty_digest = event("e2", "DISPATCH_INTENT", "op-1", {}).payload_digest
    journal._db.execute(
        "INSERT INTO journal_events VALUES(2,?,?,?,?,?,?)",
        ("e2", "DISPATCH_INTENT", 1, "op-1", "{}", empty_digest),
    )
    journal._db.commit()
    with pytest.raises(JournalError, match="epoch regressed"):
        journal.replay()
    journal.close()
