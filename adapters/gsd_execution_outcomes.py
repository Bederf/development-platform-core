"""Journal-backed dispatch intent and outcome classification for GSD P045 T002."""

from __future__ import annotations

from dataclasses import dataclass

from .gsd_execution_identity import OperationIdentity, OperationIdentityRegistry
from .gsd_execution_journal import JournalError, JournalEvent, JournalStore
from .gsd_execution_state import AttemptState


class OutcomeError(ValueError):
    """Raised when an intent or observation cannot be accepted safely."""


SUPPORTED_OUTCOMES = frozenset({
    AttemptState.SUCCEEDED,
    AttemptState.FAILED,
    AttemptState.TIMED_OUT,
    AttemptState.CANCELLED,
    AttemptState.UNKNOWN,
})
TERMINAL_OUTCOMES = SUPPORTED_OUTCOMES - {AttemptState.UNKNOWN}


@dataclass(frozen=True)
class IntentDecision:
    operation_id: str
    attempt_id: str
    sequence: int
    decision: str


@dataclass(frozen=True)
class OutcomeDecision:
    operation_id: str
    attempt_id: str
    outcome: AttemptState
    observation_digest: str
    sequence: int
    classification: str


class DispatchOutcomeController:
    """Record dispatch boundaries without dispatching any real work."""

    def __init__(
        self,
        journal: JournalStore,
        *,
        controller_epoch: int = 1,
        identity_registry: OperationIdentityRegistry | None = None,
    ):
        if controller_epoch < 1:
            raise OutcomeError("controller epoch must be positive")
        self.journal = journal
        self.controller_epoch = controller_epoch
        self.identity_registry = identity_registry or OperationIdentityRegistry(
            journal, controller_epoch=controller_epoch
        )

    def record_intent(
        self,
        operation_id: str,
        *,
        attempt_id: str,
        input_digest: str,
        fault: str | None = None,
    ) -> IntentDecision:
        self._identity(operation_id, attempt_id)
        if not isinstance(input_digest, str) or not input_digest:
            raise OutcomeError("canonical input digest is required")
        try:
            identity = self.identity_registry.register(
                OperationIdentity(operation_id, input_digest), attempt_id=attempt_id
            )
        except ValueError as exc:
            raise OutcomeError(str(exc)) from exc
        if identity.attempt_id != attempt_id:
            raise OutcomeError("operation already has a different attempt identity")
        events = self._operation_events(operation_id)
        for event in events:
            if event.event_type not in {"DISPATCH_INTENT", "DISPATCH_OBSERVED"}:
                continue
            existing_attempt = event.payload.get("attempt_id")
            if existing_attempt != attempt_id:
                raise OutcomeError("operation already has a different attempt identity")
            if event.event_type == "DISPATCH_OBSERVED":
                return IntentDecision(operation_id, attempt_id, event.sequence or 0, "already_observed")
            return IntentDecision(operation_id, attempt_id, event.sequence or 0, "duplicate")
        event = JournalEvent(
            event_id=f"dispatch-intent:{operation_id}:{attempt_id}",
            event_type="DISPATCH_INTENT",
            controller_epoch=self.controller_epoch,
            operation_id=operation_id,
            payload={
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "input_digest": input_digest,
            },
        )
        try:
            committed = self.journal.append(event, fault=fault)
        except JournalError as exc:
            raise OutcomeError("dispatch intent could not be committed") from exc
        return IntentDecision(operation_id, attempt_id, committed.sequence or 0, "committed")

    def record_observation(
        self,
        operation_id: str,
        *,
        attempt_id: str,
        outcome: AttemptState,
        observation_digest: str,
    ) -> OutcomeDecision:
        self._identity(operation_id, attempt_id)
        if type(outcome) is not AttemptState or outcome not in SUPPORTED_OUTCOMES:
            raise OutcomeError("unsupported observation outcome; fail closed")
        if not isinstance(observation_digest, str) or not observation_digest:
            raise OutcomeError("observation digest is required")
        events = self._operation_events(operation_id)
        intents = [
            event for event in events
            if event.event_type == "DISPATCH_INTENT"
        ]
        if any(event.payload.get("attempt_id") != attempt_id for event in intents):
            raise OutcomeError("operation already has a different attempt identity")
        if not any(event.payload.get("attempt_id") == attempt_id for event in intents):
            raise OutcomeError("observation requires a committed dispatch intent")
        observations = [
            event for event in events
            if event.event_type == "DISPATCH_OBSERVED"
            and event.payload.get("attempt_id") == attempt_id
        ]
        for event in observations:
            prior_outcome = self._outcome(event)
            prior_digest = event.payload.get("observation_digest")
            if prior_digest == observation_digest:
                if prior_outcome is not outcome:
                    raise OutcomeError("conflicting observation payload; fail closed")
                return OutcomeDecision(operation_id, attempt_id, outcome, observation_digest, event.sequence or 0, "duplicate")
            if prior_outcome is AttemptState.UNKNOWN:
                raise OutcomeError("unknown outcome requires explicit reconciliation")
            if prior_digest == observation_digest:
                raise OutcomeError("conflicting observation payload; fail closed")

        event = JournalEvent(
            event_id=f"dispatch-observation:{operation_id}:{attempt_id}:{observation_digest}",
            event_type="DISPATCH_OBSERVED",
            controller_epoch=self.controller_epoch,
            operation_id=operation_id,
            payload={
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "outcome": outcome.value,
                "observation_digest": observation_digest,
            },
        )
        try:
            committed = self.journal.append(event)
        except JournalError as exc:
            raise OutcomeError("dispatch observation could not be committed") from exc
        classification = "committed" if not observations else "late"
        return OutcomeDecision(
            operation_id,
            attempt_id,
            outcome,
            observation_digest,
            committed.sequence or 0,
            classification,
        )

    def _operation_events(self, operation_id: str) -> tuple[JournalEvent, ...]:
        return tuple(event for event in self.journal.events() if event.operation_id == operation_id)

    @staticmethod
    def _identity(operation_id: str, attempt_id: str) -> None:
        if not isinstance(operation_id, str) or not operation_id:
            raise OutcomeError("operation_id is required")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise OutcomeError("attempt_id is required")

    @staticmethod
    def _outcome(event: JournalEvent) -> AttemptState:
        try:
            return AttemptState(event.payload["outcome"])
        except (KeyError, ValueError) as exc:
            raise OutcomeError("committed observation outcome is malformed") from exc
