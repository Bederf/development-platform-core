from __future__ import annotations

import pytest

from adapters.gsd_execution_identity import (
    OperationIdentity,
    OperationIdentityError,
    OperationIdentityRegistry,
)
from adapters.gsd_execution_journal import JournalStore


def test_same_operation_and_input_commits_once(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    registry = OperationIdentityRegistry(journal)
    identity = OperationIdentity.from_input("op-1", {"task": "a", "value": 1})

    first = registry.register(identity, attempt_id="attempt-1")
    duplicate = registry.register(identity, attempt_id="attempt-2")

    assert first == duplicate
    assert duplicate.attempt_id == "attempt-1"
    assert len(journal.events()) == 1
    journal.close()


def test_same_operation_with_different_input_fails_without_mutation(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    registry = OperationIdentityRegistry(journal)
    registry.register(OperationIdentity.from_input("op-1", {"value": 1}), attempt_id="attempt-1")

    with pytest.raises(OperationIdentityError, match="input digest differs"):
        registry.register(OperationIdentity.from_input("op-1", {"value": 2}), attempt_id="attempt-2")

    assert len(journal.events()) == 1
    journal.close()


def test_canonical_input_order_is_stable(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    registry = OperationIdentityRegistry(journal)
    first = OperationIdentity.from_input("op-1", {"b": 2, "a": 1})
    second = OperationIdentity.from_input("op-1", {"a": 1, "b": 2})

    registry.register(first, attempt_id="attempt-1")
    duplicate = registry.register(second, attempt_id="attempt-2")

    assert duplicate.attempt_id == "attempt-1"
    assert len(journal.events()) == 1
    journal.close()


def test_malformed_committed_identity_fails_closed(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    journal.append(
        __import__("adapters.gsd_execution_journal", fromlist=["JournalEvent"]).JournalEvent(
            "event-1",
            "OUTCOME",
            1,
            "op-1",
            {"kind": "OPERATION_DECISION", "operation_id": "op-1", "input_digest": "bad"},
        )
    )
    registry = OperationIdentityRegistry(journal)

    with pytest.raises(OperationIdentityError, match="malformed"):
        registry.register(OperationIdentity.from_input("op-1", {"a": 1}), attempt_id="attempt-1")
    journal.close()


def test_operation_identity_rejects_non_sha256_digest():
    with pytest.raises(OperationIdentityError, match="canonical SHA-256"):
        OperationIdentity("op-1", "sha256:not-a-digest")
