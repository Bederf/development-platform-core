"""Local durable journal and fail-closed replay primitives for P043.

This module deliberately stops at journal authority, projection replay and
recovery evidence. It does not admit tasks, dispatch providers or own
workspaces.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from adapters.gsd_execution_state import AttemptState, ExecutionStateError, transition_attempt


class JournalError(ValueError):
    """Raised when journal integrity, identity or replay safety fails."""


ALLOWED_EVENT_TYPES = frozenset(
    {"DISPATCH_INTENT", "DISPATCH_OBSERVED", "OUTCOME", "ATTEMPT_STATE"}
)


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class JournalEvent:
    event_id: str
    event_type: str
    controller_epoch: int
    operation_id: str
    payload: Mapping[str, Any]
    sequence: int | None = None

    @property
    def payload_digest(self) -> str:
        return _digest(self.payload)


@dataclass(frozen=True)
class ReplayProjection:
    events: tuple[JournalEvent, ...]
    attempt_states: Mapping[str, AttemptState]
    incomplete_dispatch_intents: frozenset[str]
    controller_epoch: int
    reconciled_outcomes: Mapping[str, AttemptState]

    @property
    def projection_digest(self) -> str:
        """Return a stable identity for the committed replay projection."""
        return _digest({
            "events": [
                {
                    "sequence": event.sequence,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "controller_epoch": event.controller_epoch,
                    "operation_id": event.operation_id,
                    "payload": event.payload,
                }
                for event in self.events
            ],
            "attempt_states": {
                attempt_id: state.value
                for attempt_id, state in sorted(self.attempt_states.items())
            },
            "incomplete_dispatch_intents": sorted(self.incomplete_dispatch_intents),
            "controller_epoch": self.controller_epoch,
            "reconciled_outcomes": {
                attempt_id: outcome.value
                for attempt_id, outcome in sorted(self.reconciled_outcomes.items())
            },
        })


class JournalStore:
    """SQLite-backed local journal with transactional append and replay."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Multiple local controllers may initialize the same journal
        # concurrently. Serialize only this SQLite/WAL setup step; normal
        # journal transactions retain SQLite's own transactional semantics.
        with self._initialization_lock():
            self._db = sqlite3.connect(self.path, timeout=30.0)
            self._db.execute("PRAGMA busy_timeout=30000")
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS journal_events (
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    controller_epoch INTEGER NOT NULL,
                    operation_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_digest TEXT NOT NULL
                )"""
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS journal_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._db.commit()

    @contextmanager
    def _initialization_lock(self):
        lock_path = self.path.with_name(self.path.name + ".init.lock")
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def close(self) -> None:
        self._db.close()

    def set_controller_epoch(self, epoch: int) -> None:
        if epoch < 1:
            raise JournalError("controller epoch must be positive")
        current = self.controller_epoch
        if epoch < current:
            raise JournalError("controller epoch cannot move backwards")
        self._db.execute(
            "INSERT INTO journal_meta(key,value) VALUES('controller_epoch',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(epoch),),
        )
        self._db.commit()

    @property
    def controller_epoch(self) -> int:
        row = self._db.execute(
            "SELECT value FROM journal_meta WHERE key='controller_epoch'"
        ).fetchone()
        return int(row[0]) if row else 0

    def append(self, event: JournalEvent, *, fault: str | None = None) -> JournalEvent:
        return self.append_batch((event,), fault=fault)[0]

    def append_batch(
        self,
        events: tuple[JournalEvent, ...] | list[JournalEvent],
        *,
        fault: str | None = None,
    ) -> tuple[JournalEvent, ...]:
        """Append one journal transaction containing one or more events."""

        if fault not in {None, "before_commit", "after_commit"}:
            raise JournalError("unknown journal fault point")
        batch = tuple(events)
        if not batch:
            raise JournalError("journal batch cannot be empty")
        for event in batch:
            if not event.event_id or not event.event_type or not event.operation_id:
                raise JournalError("event identity is required")
            if event.event_type not in ALLOWED_EVENT_TYPES:
                raise JournalError("unknown journal event type")
            if event.controller_epoch < 1:
                raise JournalError("event controller epoch must be positive")
        committed = False
        results: list[JournalEvent] = []
        try:
            with self._db:
                for event in batch:
                    payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"))
                    digest = event.payload_digest
                    existing = self._db.execute(
                        "SELECT sequence,event_type,controller_epoch,operation_id,payload_digest,payload "
                        "FROM journal_events WHERE event_id=?",
                        (event.event_id,),
                    ).fetchone()
                    if existing:
                        if existing[1:5] != (
                            event.event_type,
                            event.controller_epoch,
                            event.operation_id,
                            digest,
                        ):
                            raise JournalError("conflicting duplicate event identity")
                        results.append(JournalEvent(
                            event.event_id,
                            event.event_type,
                            event.controller_epoch,
                            event.operation_id,
                            json.loads(existing[5]),
                            existing[0],
                        ))
                        continue
                    if event.controller_epoch < self.controller_epoch:
                        raise JournalError("stale controller epoch cannot append")
                    self._db.execute(
                        "INSERT INTO journal_meta(key,value) VALUES('controller_epoch',?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (str(event.controller_epoch),),
                    )
                    sequence = self._db.execute(
                        "SELECT COALESCE(MAX(sequence),0)+1 FROM journal_events"
                    ).fetchone()[0]
                    self._db.execute(
                        "INSERT INTO journal_events VALUES(?,?,?,?,?,?,?)",
                        (sequence, event.event_id, event.event_type, event.controller_epoch,
                         event.operation_id, payload, digest),
                    )
                    results.append(JournalEvent(
                        event.event_id,
                        event.event_type,
                        event.controller_epoch,
                        event.operation_id,
                        event.payload,
                        sequence,
                    ))
                if fault == "before_commit":
                    raise JournalError("injected crash before journal commit")
            committed = True
        except sqlite3.IntegrityError as exc:
            raise JournalError("journal event identity conflict") from exc
        if fault == "after_commit" and committed:
            raise JournalError("injected crash after journal commit")
        return tuple(results)

    def events(self) -> tuple[JournalEvent, ...]:
        rows = self._db.execute(
            "SELECT sequence,event_id,event_type,controller_epoch,operation_id,payload "
            "FROM journal_events ORDER BY sequence"
        ).fetchall()
        return tuple(
            JournalEvent(b, c, d, e, json.loads(f), a)
            for a, b, c, d, e, f in rows
        )

    def replay(self) -> ReplayProjection:
        rows = self._db.execute(
            "SELECT sequence,event_id,event_type,controller_epoch,operation_id,payload,payload_digest "
            "FROM journal_events ORDER BY sequence"
        ).fetchall()
        expected = 1
        events: list[JournalEvent] = []
        attempts: dict[str, AttemptState] = {}
        reconciled_outcomes: dict[str, AttemptState] = {}
        intents: set[str] = set()
        epoch = self.controller_epoch
        previous_epoch = 0
        for sequence, event_id, event_type, event_epoch, operation_id, raw_payload, digest in rows:
            if sequence != expected:
                raise JournalError("journal sequence gap during replay")
            if event_type not in ALLOWED_EVENT_TYPES:
                raise JournalError("unknown journal event type during replay")
            payload = json.loads(raw_payload)
            if _digest(payload) != digest:
                raise JournalError("journal payload digest conflict during replay")
            if event_epoch < previous_epoch:
                raise JournalError("controller epoch regressed during replay")
            event = JournalEvent(
                event_id, event_type, event_epoch, operation_id, payload, sequence
            )
            events.append(event)
            if event_type == "DISPATCH_INTENT":
                intents.add(operation_id)
            elif event_type in {"DISPATCH_OBSERVED", "OUTCOME"}:
                intents.discard(operation_id)
                if (
                    event_type == "OUTCOME"
                    and payload.get("kind") == "UNKNOWN_RECONCILIATION"
                    and payload.get("decision") == "CONFIRMED_TERMINAL"
                ):
                    attempt_id = payload.get("attempt_id")
                    try:
                        outcome = AttemptState(payload.get("confirmed_outcome"))
                    except (TypeError, ValueError) as exc:
                        raise JournalError("invalid confirmed reconciliation outcome during replay") from exc
                    if outcome not in {
                        AttemptState.SUCCEEDED,
                        AttemptState.FAILED,
                        AttemptState.TIMED_OUT,
                        AttemptState.CANCELLED,
                    } or not isinstance(attempt_id, str) or not attempt_id:
                        raise JournalError("invalid confirmed reconciliation projection during replay")
                    prior = reconciled_outcomes.get(attempt_id)
                    if prior is not None and prior is not outcome:
                        raise JournalError("conflicting confirmed reconciliation outcomes during replay")
                    reconciled_outcomes[attempt_id] = outcome
            elif event_type == "ATTEMPT_STATE":
                attempt_id = str(payload.get("attempt_id", ""))
                try:
                    state = AttemptState(str(payload.get("state", "")))
                except ValueError as exc:
                    raise JournalError("invalid attempt state during replay") from exc
                previous = attempts.get(attempt_id)
                if previous is None:
                    if state is not AttemptState.CREATED:
                        raise JournalError("attempt projection must begin at CREATED")
                else:
                    try:
                        transition_attempt(previous, state)
                    except ExecutionStateError as exc:
                        raise JournalError("invalid attempt transition during replay") from exc
                attempts[attempt_id] = state
            previous_epoch = event_epoch
            expected += 1
        return ReplayProjection(
            tuple(events), dict(attempts), frozenset(intents), epoch,
            dict(reconciled_outcomes),
        )
