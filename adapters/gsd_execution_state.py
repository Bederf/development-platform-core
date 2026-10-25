"""Pure GSD execution-control task and attempt state semantics.

This module deliberately has no filesystem, provider, network, workspace or
harness dependency. Journal sequence values are supplied by the future
controller journal and are used here only as the deterministic ordering
abstraction required by ADR-030.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class ExecutionStateError(ValueError):
    """Raised when a state transition or observation is unsafe."""


class TaskState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    ADMITTED = "ADMITTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class AttemptState(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


TASK_TRANSITIONS: Mapping[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.READY}),
    TaskState.READY: frozenset({TaskState.ADMITTED}),
    TaskState.ADMITTED: frozenset({TaskState.RUNNING}),
    TaskState.RUNNING: frozenset({
        TaskState.SUCCEEDED,
        TaskState.FAILED,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
        TaskState.UNKNOWN,
    }),
    TaskState.UNKNOWN: frozenset({
        TaskState.RUNNING,
        TaskState.SUCCEEDED,
        TaskState.FAILED,
        TaskState.BLOCKED,
    }),
    TaskState.SUCCEEDED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.BLOCKED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


ATTEMPT_TRANSITIONS: Mapping[AttemptState, frozenset[AttemptState]] = {
    AttemptState.CREATED: frozenset({AttemptState.DISPATCHED}),
    AttemptState.DISPATCHED: frozenset({
        AttemptState.RUNNING,
        AttemptState.UNKNOWN,
    }),
    AttemptState.RUNNING: frozenset({
        AttemptState.SUCCEEDED,
        AttemptState.FAILED,
        AttemptState.TIMED_OUT,
        AttemptState.CANCEL_REQUESTED,
        AttemptState.UNKNOWN,
    }),
    AttemptState.CANCEL_REQUESTED: frozenset({
        AttemptState.CANCELLED,
        AttemptState.UNKNOWN,
    }),
    AttemptState.UNKNOWN: frozenset({
        AttemptState.RUNNING,
        AttemptState.SUCCEEDED,
        AttemptState.FAILED,
        AttemptState.BLOCKED,
    }),
    AttemptState.SUCCEEDED: frozenset(),
    AttemptState.FAILED: frozenset(),
    AttemptState.TIMED_OUT: frozenset(),
    AttemptState.CANCELLED: frozenset(),
    AttemptState.BLOCKED: frozenset(),
}


TERMINAL_ATTEMPT_STATES = frozenset({
    AttemptState.SUCCEEDED,
    AttemptState.FAILED,
    AttemptState.TIMED_OUT,
    AttemptState.CANCELLED,
})


@dataclass(frozen=True)
class TerminalObservation:
    """A journal-ordered terminal observation supplied to the pure model."""

    sequence: int
    outcome: AttemptState
    operation_id: str
    observation_digest: str

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ExecutionStateError("journal sequence must be positive")
        if type(self.outcome) is not AttemptState:
            raise ExecutionStateError("terminal observation outcome must be an attempt state")
        if self.outcome not in TERMINAL_ATTEMPT_STATES:
            raise ExecutionStateError("terminal observation has a non-terminal outcome")
        if not self.operation_id or not self.observation_digest:
            raise ExecutionStateError("terminal observation identity is required")


@dataclass(frozen=True)
class TerminalResolution:
    winner: TerminalObservation
    late: tuple[TerminalObservation, ...]
    duplicates: tuple[TerminalObservation, ...]


@dataclass(frozen=True)
class RetryProjection:
    """Pure retry lineage and initial state projection."""

    prior_attempt_id: str
    new_attempt_id: str
    prior_state: AttemptState
    projected_state: AttemptState


def _coerce_task(state: TaskState | str) -> TaskState:
    if type(state) is not str and type(state) is not TaskState:
        raise ExecutionStateError(f"unknown task state: {state!r}")
    try:
        return state if isinstance(state, TaskState) else TaskState(state)
    except ValueError as exc:
        raise ExecutionStateError(f"unknown task state: {state!r}") from exc


def _coerce_attempt(state: AttemptState | str) -> AttemptState:
    if type(state) is not str and type(state) is not AttemptState:
        raise ExecutionStateError(f"unknown attempt state: {state!r}")
    try:
        return state if isinstance(state, AttemptState) else AttemptState(state)
    except ValueError as exc:
        raise ExecutionStateError(f"unknown attempt state: {state!r}") from exc


def transition_task(
    current: TaskState | str,
    requested: TaskState | str,
    *,
    accepted_terminal_observation: TerminalObservation | None = None,
) -> TaskState:
    """Apply one legal task transition; success requires accepted attempt evidence."""

    current_state = _coerce_task(current)
    requested_state = _coerce_task(requested)
    if requested_state is TaskState.SUCCEEDED:
        if type(accepted_terminal_observation) is not TerminalObservation:
            raise ExecutionStateError("task success requires an accepted terminal observation")
        if accepted_terminal_observation.outcome is not AttemptState.SUCCEEDED:
            raise ExecutionStateError("task success requires an accepted successful attempt")
    if requested_state not in TASK_TRANSITIONS[current_state]:
        raise ExecutionStateError(
            f"illegal task transition: {current_state.value} -> {requested_state.value}"
        )
    return requested_state


def transition_attempt(current: AttemptState | str, requested: AttemptState | str) -> AttemptState:
    """Apply one legal attempt transition; terminal states are immutable."""

    current_state = _coerce_attempt(current)
    requested_state = _coerce_attempt(requested)
    if requested_state not in ATTEMPT_TRANSITIONS[current_state]:
        raise ExecutionStateError(
            f"illegal attempt transition: {current_state.value} -> {requested_state.value}"
        )
    return requested_state


def resolve_terminal_observations(observations: Iterable[TerminalObservation]) -> TerminalResolution:
    """Resolve terminal races by journal sequence, never wall-clock order."""

    ordered = tuple(observations)
    if not ordered:
        raise ExecutionStateError("terminal observations are required")
    operations = {item.operation_id for item in ordered}
    if len(operations) != 1:
        raise ExecutionStateError("terminal observations have conflicting operation identities")
    digests = {}
    for item in ordered:
        prior_outcome = digests.setdefault(item.observation_digest, item.outcome)
        if prior_outcome is not item.outcome:
            raise ExecutionStateError("conflicting terminal payloads share an observation digest")
    sequences = [item.sequence for item in ordered]
    for sequence in set(sequences):
        same_sequence = [item for item in ordered if item.sequence == sequence]
        if len({(item.outcome, item.observation_digest) for item in same_sequence}) > 1:
            raise ExecutionStateError("ambiguous terminal sequence; fail closed")
    winner = min(ordered, key=lambda item: item.sequence)
    duplicates = tuple(item for item in ordered if item.observation_digest == winner.observation_digest and item is not winner)
    late = tuple(item for item in ordered if item not in duplicates and item is not winner)
    return TerminalResolution(winner=winner, late=late, duplicates=duplicates)


def classify_observation(
    committed: TerminalObservation,
    incoming: TerminalObservation,
) -> str:
    """Classify a later observation without allowing it to mutate commitment."""

    if committed.operation_id != incoming.operation_id:
        raise ExecutionStateError("observation operation identity mismatch")
    if committed.observation_digest == incoming.observation_digest:
        if committed.outcome is not incoming.outcome:
            raise ExecutionStateError("conflicting observation payload; fail closed")
        if incoming.sequence < committed.sequence:
            raise ExecutionStateError("conflicting observation sequence; fail closed")
        return "duplicate"
    if incoming.sequence <= committed.sequence:
        raise ExecutionStateError("conflicting observation sequence; fail closed")
    return "late"


def authorize_retry(
    prior_state: AttemptState | str,
    *,
    new_attempt_id: str,
    prior_attempt_id: str,
    task_retry_safe: bool,
    qualified_unknown_replay: bool = False,
    concurrent_owner: bool = False,
) -> bool:
    """Authorize only a new, explicitly safe retry lineage."""

    state = _coerce_attempt(prior_state)
    if not new_attempt_id or not prior_attempt_id or new_attempt_id == prior_attempt_id:
        raise ExecutionStateError("retry requires a distinct attempt identity")
    if concurrent_owner:
        raise ExecutionStateError("retry is unsafe while a concurrent owner remains")
    if not task_retry_safe:
        raise ExecutionStateError("task is not classified as retry-safe")
    if state in {AttemptState.FAILED, AttemptState.TIMED_OUT}:
        return True
    if state is AttemptState.UNKNOWN and qualified_unknown_replay:
        return True
    raise ExecutionStateError("attempt state is not safely retryable")


def project_retry(
    prior_state: AttemptState | str,
    *,
    new_attempt_id: str,
    prior_attempt_id: str,
    task_retry_safe: bool,
    qualified_unknown_replay: bool = False,
    concurrent_owner: bool = False,
) -> RetryProjection:
    """Project an explicitly authorized retry without mutating prior state."""

    state = _coerce_attempt(prior_state)
    authorize_retry(
        state,
        new_attempt_id=new_attempt_id,
        prior_attempt_id=prior_attempt_id,
        task_retry_safe=task_retry_safe,
        qualified_unknown_replay=qualified_unknown_replay,
        concurrent_owner=concurrent_owner,
    )
    return RetryProjection(
        prior_attempt_id=prior_attempt_id,
        new_attempt_id=new_attempt_id,
        prior_state=state,
        projected_state=AttemptState.CREATED,
    )
