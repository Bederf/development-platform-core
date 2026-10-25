"""Fail-closed GSD–Forge verification lifecycle primitives.

This module owns attempt identity, durable lifecycle state, result binding, and
process-ownership validation. It deliberately does not launch Forge or send
signals to processes; those effects remain an integration responsibility.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

import fcntl


LifecycleState = Literal[
    "AGENT_COMPLETE",
    "VERIFICATION_PENDING",
    "FORGE_RUNNING",
    "DONE",
    "VERIFICATION_FAILED",
    "VERIFICATION_TIMEOUT",
    "VERIFICATION_INTERRUPTED",
    "VERIFICATION_UNKNOWN",
    "FAILED",
    "ABANDONED",
]

NON_SUCCESS_STATES = frozenset(
    {
        "VERIFICATION_FAILED",
        "VERIFICATION_TIMEOUT",
        "VERIFICATION_INTERRUPTED",
        "VERIFICATION_UNKNOWN",
        "FAILED",
        "ABANDONED",
    }
)


class VerificationLifecycleError(ValueError):
    """Base error for invalid lifecycle operations."""


class DuplicateVerificationAttempt(VerificationLifecycleError):
    """Raised when an active attempt already owns a repository."""


class ImmutableAttemptError(VerificationLifecycleError):
    """Raised when immutable attempt identity is changed."""


class RecoveryDenied(VerificationLifecycleError):
    """Raised when recovery would manufacture or adopt verification evidence."""


@dataclass(frozen=True)
class VerificationIdentity:
    verification_attempt_id: str
    gsd_session_id: str
    forge_session_id: str
    execution_id: str
    attempt_id: str
    repository: str
    baseline: str
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "lineage", tuple(self.lineage))
        for name, value in asdict(self).items():
            if name == "lineage":
                if any(not isinstance(item, str) or not item for item in value):
                    raise VerificationLifecycleError("lineage entries must be non-empty strings")
                continue
            if not isinstance(value, str) or not value:
                raise VerificationLifecycleError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class ForgeResult:
    verification_attempt_id: str
    gsd_session_id: str
    forge_session_id: str
    execution_id: str
    attempt_id: str
    repository: str
    baseline: str
    lineage: tuple[str, ...]
    status: Literal["PASS", "FAIL"]
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lineage", tuple(self.lineage))
        if self.status not in {"PASS", "FAIL"}:
            raise VerificationLifecycleError("Forge result status must be PASS or FAIL")


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    pgid: int
    session_id: int
    start_time: str
    executable: str
    command_identity: str
    verification_attempt_id: str


@dataclass
class VerificationAttempt:
    identity: VerificationIdentity
    state: LifecycleState
    agent_exit_code: int | None = None
    terminal_reason: str | None = None
    process: ProcessIdentity | None = None
    history: list[dict[str, str]] = field(default_factory=list)

    def record(self, state: LifecycleState, reason: str) -> None:
        self.state = state
        self.terminal_reason = reason if state != "FORGE_RUNNING" else None
        self.history.append({"state": state, "reason": reason})


class VerificationAttemptStore:
    """Small JSON-backed durable store for immutable attempt records."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, attempt: VerificationAttempt) -> None:
        target = self._path(attempt.identity.verification_attempt_id)
        payload = self._serialize(attempt)
        fd, temporary = tempfile.mkstemp(prefix=".attempt-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Serialize repository ownership decisions across GSD processes."""
        lock_path = self.root / ".verification-lifecycle.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def load(self, verification_attempt_id: str) -> VerificationAttempt:
        path = self._path(verification_attempt_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema") != "gsd-forge-verification-attempt.v1":
                raise VerificationLifecycleError("unsupported verification attempt schema")
            identity = VerificationIdentity(**payload["identity"])
            process = payload.get("process")
            return VerificationAttempt(
                identity=identity,
                state=payload["state"],
                agent_exit_code=payload.get("agent_exit_code"),
                terminal_reason=payload.get("terminal_reason"),
                process=ProcessIdentity(**process) if process else None,
                history=payload.get("history", []),
            )
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise VerificationLifecycleError("verification attempt state is missing or corrupt") from exc

    def exists(self, verification_attempt_id: str) -> bool:
        return self._path(verification_attempt_id).exists()

    def all(self) -> list[VerificationAttempt]:
        attempts: list[VerificationAttempt] = []
        for path in sorted(self.root.glob("*.json")):
            attempts.append(self.load(path.stem))
        return attempts

    def active_for_repository(self, repository: str) -> VerificationAttempt | None:
        active = {"AGENT_COMPLETE", "VERIFICATION_PENDING", "FORGE_RUNNING"}
        matches = [
            attempt
            for attempt in self.all()
            if attempt.identity.repository == repository and attempt.state in active
        ]
        if len(matches) > 1:
            raise VerificationLifecycleError("repository has multiple active verification owners")
        return matches[0] if matches else None

    def _path(self, verification_attempt_id: str) -> Path:
        if not verification_attempt_id or Path(verification_attempt_id).name != verification_attempt_id:
            raise VerificationLifecycleError("invalid verification attempt id")
        return self.root / f"{verification_attempt_id}.json"

    @staticmethod
    def _serialize(attempt: VerificationAttempt) -> dict[str, Any]:
        return {
            "schema": "gsd-forge-verification-attempt.v1",
            "identity": asdict(attempt.identity),
            "state": attempt.state,
            "agent_exit_code": attempt.agent_exit_code,
            "terminal_reason": attempt.terminal_reason,
            "process": asdict(attempt.process) if attempt.process else None,
            "history": attempt.history,
        }


class VerificationLifecycle:
    """Fail-closed lifecycle coordinator for one durable attempt store."""

    def __init__(self, store: VerificationAttemptStore | Path | str) -> None:
        self.store = store if isinstance(store, VerificationAttemptStore) else VerificationAttemptStore(store)

    def create_attempt(
        self,
        *,
        gsd_session_id: str,
        forge_session_id: str,
        execution_id: str,
        repository: str,
        baseline: str,
        lineage: tuple[str, ...] = (),
        attempt_id: str | None = None,
        verification_attempt_id: str | None = None,
    ) -> VerificationAttempt:
        with self.store.exclusive():
            if self.store.active_for_repository(repository) is not None:
                raise DuplicateVerificationAttempt(repository)
            if verification_attempt_id is not None and self.store.exists(verification_attempt_id):
                raise ImmutableAttemptError("verification_attempt_id cannot be reused")
            attempt = VerificationAttempt(
                identity=VerificationIdentity(
                    verification_attempt_id=verification_attempt_id or f"vat-{uuid.uuid4().hex}",
                    gsd_session_id=gsd_session_id,
                    forge_session_id=forge_session_id,
                    execution_id=execution_id,
                    attempt_id=attempt_id or f"attempt-{uuid.uuid4().hex}",
                    repository=repository,
                    baseline=baseline,
                    lineage=lineage,
                ),
                state="AGENT_COMPLETE",
            )
            attempt.history.append({"state": "AGENT_COMPLETE", "reason": "agent_completed"})
            self.store.save(attempt)
            return attempt

    def transition(self, attempt_id: str, state: LifecycleState, reason: str) -> VerificationAttempt:
        attempt = self.store.load(attempt_id)
        allowed: dict[LifecycleState, set[LifecycleState]] = {
            "AGENT_COMPLETE": {"VERIFICATION_PENDING", "FAILED"},
            "VERIFICATION_PENDING": {"FORGE_RUNNING", "FAILED", "VERIFICATION_UNKNOWN"},
            "FORGE_RUNNING": {
                "DONE",
                "VERIFICATION_FAILED",
                "VERIFICATION_TIMEOUT",
                "VERIFICATION_INTERRUPTED",
                "VERIFICATION_UNKNOWN",
                "FAILED",
            },
        }
        if state not in allowed.get(attempt.state, set()):
            raise VerificationLifecycleError(f"invalid transition {attempt.state} -> {state}")
        attempt.record(state, reason)
        self.store.save(attempt)
        return attempt

    def apply_result(self, result: ForgeResult) -> tuple[VerificationAttempt, bool]:
        attempt = self.store.load(result.verification_attempt_id)
        if not self.exact_match(attempt.identity, result):
            return attempt, False
        if attempt.state != "FORGE_RUNNING":
            return attempt, False
        next_state: LifecycleState = "DONE" if result.status == "PASS" else "VERIFICATION_FAILED"
        attempt.record(next_state, f"forge_{result.status.lower()}")
        self.store.save(attempt)
        return attempt, True

    def timeout(self, attempt_id: str) -> VerificationAttempt:
        return self.transition(attempt_id, "VERIFICATION_TIMEOUT", "verification_deadline_expired")

    def interrupt(self, attempt_id: str) -> VerificationAttempt:
        return self.transition(attempt_id, "VERIFICATION_INTERRUPTED", "verification_interrupted")

    def reconcile_restart(self, attempt_id: str, forge_state: str | None) -> VerificationAttempt:
        attempt = self.store.load(attempt_id)
        if attempt.state not in {"AGENT_COMPLETE", "VERIFICATION_PENDING", "FORGE_RUNNING"}:
            return attempt
        if forge_state != "completed_bound_result":
            attempt.record("VERIFICATION_UNKNOWN", "restart_reconciliation_incomplete")
            self.store.save(attempt)
        return attempt

    def manual_recover(self, attempt_id: str, action: Literal["abandon", "unresolved", "new_attempt"]) -> VerificationAttempt:
        attempt = self.store.load(attempt_id)
        if action == "abandon":
            if attempt.state in NON_SUCCESS_STATES or attempt.state == "DONE":
                return attempt
            attempt.record("ABANDONED", "operator_abandoned_verification")
            self.store.save(attempt)
            return attempt
        if action == "unresolved":
            if attempt.state == "DONE":
                raise RecoveryDenied("completed attempt cannot be made unresolved")
            if attempt.state not in NON_SUCCESS_STATES:
                attempt.record("VERIFICATION_UNKNOWN", "operator_marked_unresolved")
                self.store.save(attempt)
            return attempt
        raise RecoveryDenied("manual recovery cannot manufacture PASS; create a new attempt explicitly")

    @staticmethod
    def exact_match(identity: VerificationIdentity, result: ForgeResult) -> bool:
        return (
            identity.verification_attempt_id == result.verification_attempt_id
            and identity.gsd_session_id == result.gsd_session_id
            and identity.forge_session_id == result.forge_session_id
            and identity.execution_id == result.execution_id
            and identity.attempt_id == result.attempt_id
            and identity.repository == result.repository
            and identity.baseline == result.baseline
            and identity.lineage == result.lineage
        )

    @staticmethod
    def owns_process(expected: ProcessIdentity, observed: ProcessIdentity) -> bool:
        return (
            expected.verification_attempt_id == observed.verification_attempt_id
            and expected.pid == observed.pid
            and expected.pgid == observed.pgid
            and expected.session_id == observed.session_id
            and expected.start_time == observed.start_time
            and expected.executable == observed.executable
            and expected.command_identity == observed.command_identity
        )

    @classmethod
    def cleanup_owned_process(
        cls,
        expected: ProcessIdentity,
        observed: ProcessIdentity,
        signal: Callable[[int], None],
    ) -> bool:
        """Signal only a process whose identity was revalidated immediately.

        The caller supplies the fresh observation and signal operation so this
        module cannot accidentally discover or kill an unrelated process.
        """
        if not cls.owns_process(expected, observed):
            return False
        signal(observed.pgid)
        return True
