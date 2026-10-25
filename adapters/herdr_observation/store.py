"""Small transactional inbox/outbox store for observation adapter state."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass
from time import monotonic
from time import time


@dataclass(frozen=True)
class BufferEviction:
    event_id: str
    reason: str


class StoragePressureError(RuntimeError):
    """Durable observation storage cannot accept another transaction."""


_STORAGE_PRESSURE_MARKERS = ("disk", "full", "readonly", "read-only")


def _is_storage_pressure(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _STORAGE_PRESSURE_MARKERS)


class ObservationStore:
    def __init__(self, path: str = ":memory:", *, max_count: int = 1000, max_bytes: int = 1_000_000, max_age_seconds: float = 86400):
        if min(max_count, max_bytes) < 1 or max_age_seconds <= 0:
            raise ValueError("store limits must be positive")
        self.max_count, self.max_bytes, self.max_age_seconds = max_count, max_bytes, max_age_seconds
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS inbox (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, projected INTEGER NOT NULL DEFAULT 0, received_at REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS outbox (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS checkpoints (source TEXT PRIMARY KEY, high_water INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS execution_checkpoints (execution_id TEXT PRIMARY KEY, high_water INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS unattributed (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, reason TEXT NOT NULL, received_at REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS dispositions (event_id TEXT PRIMARY KEY, disposition TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evictions (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, source TEXT NOT NULL, reason TEXT NOT NULL, evicted_at REAL NOT NULL);
        """)
        # Preserve compatibility with an early development database created
        # before received_at was introduced.
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(inbox)")}
        if "received_at" not in columns:
            self.db.execute("ALTER TABLE inbox ADD COLUMN received_at REAL NOT NULL DEFAULT 0")
        outbox_columns = {row[1] for row in self.db.execute("PRAGMA table_info(outbox)")}
        if "created_at" not in outbox_columns:
            self.db.execute("ALTER TABLE outbox ADD COLUMN created_at REAL NOT NULL DEFAULT 0")
        unattributed_columns = {row[1] for row in self.db.execute("PRAGMA table_info(unattributed)")}
        if "received_at" not in unattributed_columns:
            self.db.execute("ALTER TABLE unattributed ADD COLUMN received_at REAL NOT NULL DEFAULT 0")
        self.db.commit()

    @contextmanager
    def _transaction(self):
        try:
            with self.db:
                yield
        except sqlite3.OperationalError as exc:
            if _is_storage_pressure(exc):
                raise StoragePressureError("Herdr observation storage pressure") from exc
            raise

    def receive(self, event: dict) -> bool:
        """Atomically admit once; duplicate delivery has no second effect."""
        with self._transaction():
            result = self.db.execute("INSERT OR IGNORE INTO inbox(event_id,payload,received_at) VALUES (?,?,?)", (event["event_id"], json.dumps(event, sort_keys=True), time()))
            if result.rowcount:
                self._trim_table("inbox", "projected=0", "event_id", "payload", "received_at")
        return result.rowcount == 1

    def project_once(self, event_id: str, result: dict) -> bool:
        with self._transaction():
            row = self.db.execute("SELECT projected FROM inbox WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            if row[0]:
                return False
            self.db.execute("INSERT OR IGNORE INTO outbox(event_id,payload,created_at) VALUES (?,?,?)", (event_id, json.dumps(result, sort_keys=True), time()))
            self._trim_table("outbox", "1=1", "event_id", "payload", "created_at")
            self.db.execute("UPDATE inbox SET projected=1 WHERE event_id=?", (event_id,))
        return True

    def pending(self) -> list[dict]:
        rows = self.db.execute("SELECT payload FROM inbox WHERE projected=0 ORDER BY rowid").fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_unattributed(self, event: dict, reason: str) -> bool:
        """Persist an observation that cannot yet be joined to Core identity."""
        with self._transaction():
            result = self.db.execute(
                "INSERT OR IGNORE INTO unattributed(event_id,payload,reason,received_at) VALUES (?,?,?,?)",
                (event["event_id"], json.dumps(event, sort_keys=True), reason, time()),
            )
            if result.rowcount:
                self._trim_table("unattributed", "1=1", "event_id", "payload", "received_at")
        return result.rowcount == 1

    def unattributed(self) -> list[dict]:
        rows = self.db.execute("SELECT payload FROM unattributed ORDER BY rowid").fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_disposition(self, event_id: str, disposition: str, detail: str = "") -> bool:
        with self._transaction():
            result = self.db.execute(
                "INSERT OR IGNORE INTO dispositions(event_id,disposition,detail) VALUES (?,?,?)",
                (event_id, disposition, detail),
            )
        return result.rowcount == 1

    def disposition(self, event_id: str) -> tuple[str, str] | None:
        row = self.db.execute("SELECT disposition,detail FROM dispositions WHERE event_id=?", (event_id,)).fetchone()
        return None if row is None else (str(row[0]), str(row[1]))

    def eviction_facts(self) -> list[dict]:
        rows = self.db.execute("SELECT event_id,source,reason,evicted_at FROM evictions ORDER BY id").fetchall()
        return [{"event_id": r[0], "source": r[1], "reason": r[2], "evicted_at": r[3]} for r in rows]

    def _trim_table(self, table: str, eligible: str, id_column: str, payload_column: str, received_column: str | None) -> None:
        now = time()
        if received_column:
            stale = self.db.execute(
                f"SELECT {id_column} FROM {table} WHERE {eligible} AND {received_column} > 0 AND ? - {received_column} > ? ORDER BY rowid",
                (now, self.max_age_seconds),
            ).fetchall()
            for (event_id,) in stale:
                self.db.execute(f"DELETE FROM {table} WHERE {id_column}=?", (event_id,))
                self.db.execute("INSERT INTO evictions(event_id,source,reason,evicted_at) VALUES (?,?,?,?)", (event_id, table, "age", now))
        while True:
            count = self.db.execute(f"SELECT count(*) FROM {table} WHERE {eligible}").fetchone()[0]
            byte_count = self.db.execute(f"SELECT coalesce(sum(length({payload_column})),0) FROM {table} WHERE {eligible}").fetchone()[0]
            if count <= self.max_count and byte_count <= self.max_bytes:
                return
            row = self.db.execute(f"SELECT {id_column} FROM {table} WHERE {eligible} ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                return
            self.db.execute(f"DELETE FROM {table} WHERE {id_column}=?", (row[0],))
            self.db.execute("INSERT INTO evictions(event_id,source,reason,evicted_at) VALUES (?,?,?,?)", (row[0], table, "limit", now))

    def checkpoint(self, source: str, high_water: int) -> None:
        with self._transaction():
            self.db.execute(
                "INSERT INTO checkpoints(source,high_water) VALUES (?,?) "
                "ON CONFLICT(source) DO UPDATE SET high_water=max(high_water, excluded.high_water)",
                (source, int(high_water)),
            )

    def high_water(self, source: str) -> int | None:
        row = self.db.execute("SELECT high_water FROM checkpoints WHERE source=?", (source,)).fetchone()
        return None if row is None else int(row[0])

    def checkpoint_execution(self, execution_id: str, high_water: int) -> None:
        with self._transaction():
            self.db.execute(
                "INSERT INTO execution_checkpoints(execution_id,high_water) VALUES (?,?) "
                "ON CONFLICT(execution_id) DO UPDATE SET high_water=max(high_water, excluded.high_water)",
                (execution_id, int(high_water)),
            )

    def execution_high_water(self, execution_id: str) -> int | None:
        row = self.db.execute("SELECT high_water FROM execution_checkpoints WHERE execution_id=?", (execution_id,)).fetchone()
        return None if row is None else int(row[0])


class BoundedObservationBuffer:
    """Deterministic in-memory safety valve for unattributed observations."""

    def __init__(self, *, max_count: int = 1000, max_bytes: int = 1_000_000, max_age_seconds: float = 3600):
        if min(max_count, max_bytes) < 1 or max_age_seconds <= 0:
            raise ValueError("buffer limits must be positive")
        self.max_count, self.max_bytes, self.max_age_seconds = max_count, max_bytes, max_age_seconds
        self._items = deque()
        self._bytes = 0
        self.evictions: list[BufferEviction] = []

    def append(self, event: dict) -> None:
        import json
        encoded = json.dumps(event, sort_keys=True, default=str).encode()
        now = monotonic()
        self._items.append((now, event, len(encoded)))
        self._bytes += len(encoded)
        self._trim(now)

    def _trim(self, now: float) -> None:
        while self._items and (len(self._items) > self.max_count or self._bytes > self.max_bytes or now - self._items[0][0] > self.max_age_seconds):
            created, event, size = self._items.popleft()
            self._bytes -= size
            self.evictions.append(BufferEviction(str(event.get("event_id", "")), "limit" if now - created <= self.max_age_seconds else "age"))

    def __len__(self) -> int:
        return len(self._items)
