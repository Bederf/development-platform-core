"""Unknown-outcome reconciliation and safe retry lineage for GSD P045 T003."""

from __future__ import annotations

from dataclasses import dataclass

from .gsd_execution_journal import JournalError, JournalEvent, JournalStore
from .gsd_execution_state import AttemptState, authorize_retry


class ReconciliationError(ValueError):
    """Raised when unknown evidence or retry lineage is unsafe."""


RECONCILIATION_DECISIONS = frozenset({
    "CONFIRMED_TERMINAL",
    "RETRY_SAFE",
    "NOT_RETRYABLE",
})


@dataclass(frozen=True)
class ReconciliationDecision:
    operation_id: str
    attempt_id: str
    prior_observation_digest: str
    decision: str
    evidence_digest: str
    sequence: int


@dataclass(frozen=True)
class RetryLineage:
    operation_id: str
    prior_attempt_id: str
    new_attempt_id: str
    prior_observation_digest: str
    reconciliation_evidence_digest: str
    retry_reason: str
    sequence: int


class UnknownOutcomeController:
    """Resolve unknown evidence and authorize a new attempt without dispatch."""

    def __init__(self, journal: JournalStore, *, controller_epoch: int = 1):
        if controller_epoch < 1:
            raise ReconciliationError("controller epoch must be positive")
        self.journal = journal
        self.controller_epoch = controller_epoch

    def reconcile_unknown(
        self,
        operation_id: str,
        *,
        attempt_id: str,
        prior_observation_digest: str,
        decision: str,
        evidence_digest: str,
        confirmed_outcome: AttemptState | None = None,
    ) -> ReconciliationDecision:
        self._identity(operation_id, attempt_id)
        if decision not in RECONCILIATION_DECISIONS:
            raise ReconciliationError("unsupported reconciliation decision; fail closed")
        if not prior_observation_digest or not evidence_digest:
            raise ReconciliationError("reconciliation requires prior and evidence digests")
        if decision == "CONFIRMED_TERMINAL":
            if type(confirmed_outcome) is not AttemptState or confirmed_outcome not in {
                AttemptState.SUCCEEDED,
                AttemptState.FAILED,
                AttemptState.TIMED_OUT,
                AttemptState.CANCELLED,
            }:
                raise ReconciliationError("confirmed terminal reconciliation requires a terminal outcome")
        elif confirmed_outcome is not None:
            raise ReconciliationError("terminal outcome is only valid for confirmed terminal reconciliation")
        events = self._operation_events(operation_id)
        unknown = [
            event for event in events
            if event.event_type == "DISPATCH_OBSERVED"
            and event.payload.get("attempt_id") == attempt_id
            and event.payload.get("outcome") == AttemptState.UNKNOWN.value
        ]
        if not unknown:
            raise ReconciliationError("unknown outcome evidence is missing")
        if not any(event.payload.get("observation_digest") == prior_observation_digest for event in unknown):
            raise ReconciliationError("reconciliation does not match the unknown observation")
        event_id = f"unknown-reconciliation:{operation_id}:{attempt_id}:{prior_observation_digest}"
        for event in events:
            if event.event_id != event_id:
                continue
            payload = event.payload
            if (
                payload.get("decision") != decision
                or payload.get("evidence_digest") != evidence_digest
                or payload.get("confirmed_outcome") != (
                    confirmed_outcome.value if confirmed_outcome is not None else None
                )
            ):
                raise ReconciliationError("conflicting reconciliation evidence; fail closed")
            return ReconciliationDecision(
                operation_id, attempt_id, prior_observation_digest, decision,
                evidence_digest, event.sequence or 0,
            )
        event = JournalEvent(
            event_id=event_id,
            event_type="OUTCOME",
            controller_epoch=self.controller_epoch,
            operation_id=operation_id,
            payload={
                "kind": "UNKNOWN_RECONCILIATION",
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "prior_observation_digest": prior_observation_digest,
                "decision": decision,
                "evidence_digest": evidence_digest,
                "confirmed_outcome": confirmed_outcome.value if confirmed_outcome is not None else None,
            },
        )
        try:
            committed = self.journal.append(event)
        except JournalError as exc:
            raise ReconciliationError("reconciliation evidence could not be committed") from exc
        return ReconciliationDecision(
            operation_id, attempt_id, prior_observation_digest, decision,
            evidence_digest, committed.sequence or 0,
        )

    def authorize_retry(
        self,
        operation_id: str,
        *,
        prior_attempt_id: str,
        new_attempt_id: str,
        task_retry_safe: bool,
        retry_reason: str,
    ) -> RetryLineage:
        self._identity(operation_id, prior_attempt_id)
        if not isinstance(new_attempt_id, str) or not new_attempt_id:
            raise ReconciliationError("retry requires a new attempt identity")
        if not retry_reason:
            raise ReconciliationError("retry requires an explicit reason")
        events = self._operation_events(operation_id)
        reconciliations = [
            event for event in events
            if event.event_type == "OUTCOME"
            and event.payload.get("kind") == "UNKNOWN_RECONCILIATION"
            and event.payload.get("attempt_id") == prior_attempt_id
            and event.payload.get("decision") == "RETRY_SAFE"
        ]
        if not reconciliations:
            raise ReconciliationError("safe retry requires a RETRY_SAFE reconciliation")
        reconciliation = reconciliations[-1]
        prior_digest = str(reconciliation.payload["prior_observation_digest"])
        evidence_digest = str(reconciliation.payload["evidence_digest"])
        try:
            authorize_retry(
                AttemptState.UNKNOWN,
                new_attempt_id=new_attempt_id,
                prior_attempt_id=prior_attempt_id,
                task_retry_safe=task_retry_safe,
                qualified_unknown_replay=True,
            )
        except ValueError as exc:
            raise ReconciliationError(str(exc)) from exc
        event_id = f"retry-authorization:{operation_id}:{prior_attempt_id}:{new_attempt_id}"
        for event in events:
            if event.event_id != event_id:
                continue
            payload = event.payload
            if payload.get("retry_reason") != retry_reason:
                raise ReconciliationError("conflicting retry authorization; fail closed")
            return RetryLineage(
                operation_id, prior_attempt_id, new_attempt_id, prior_digest,
                evidence_digest, retry_reason, event.sequence or 0,
            )
        retry_event = JournalEvent(
            event_id=event_id,
            event_type="OUTCOME",
            controller_epoch=self.controller_epoch,
            operation_id=operation_id,
            payload={
                "kind": "RETRY_AUTHORIZATION",
                "operation_id": operation_id,
                "prior_attempt_id": prior_attempt_id,
                "new_attempt_id": new_attempt_id,
                "prior_observation_digest": prior_digest,
                "reconciliation_evidence_digest": evidence_digest,
                "retry_reason": retry_reason,
                "projected_state": AttemptState.CREATED.value,
            },
        )
        state_event = JournalEvent(
            event_id=f"retry-attempt-created:{operation_id}:{new_attempt_id}",
            event_type="ATTEMPT_STATE",
            controller_epoch=self.controller_epoch,
            operation_id=operation_id,
            payload={
                "attempt_id": new_attempt_id,
                "state": AttemptState.CREATED.value,
                "prior_attempt_id": prior_attempt_id,
                "retry_authorization_event_id": event_id,
            },
        )
        try:
            committed_retry, _committed_state = self.journal.append_batch(
                (state_event, retry_event)
            )
        except JournalError as exc:
            raise ReconciliationError("retry authorization could not be committed") from exc
        return RetryLineage(
            operation_id, prior_attempt_id, new_attempt_id, prior_digest,
            evidence_digest, retry_reason, committed_retry.sequence or 0,
        )

    def _operation_events(self, operation_id: str) -> tuple[JournalEvent, ...]:
        return tuple(event for event in self.journal.events() if event.operation_id == operation_id)

    @staticmethod
    def _identity(operation_id: str, attempt_id: str) -> None:
        if not isinstance(operation_id, str) or not operation_id:
            raise ReconciliationError("operation_id is required")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ReconciliationError("attempt_id is required")
