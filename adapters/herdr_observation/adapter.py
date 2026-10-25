"""Composed read-only Herdr observation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from .correlation import Correlator, HerdrEvent
from .normalizer import normalize
from .projection import assert_envelope_shape, project
from .store import ObservationStore, StoragePressureError
from .transport import ReadOnlySubscription, TransportHealth, TransportError


@dataclass
class ObservationMetrics:
    received: int = 0
    admitted: int = 0
    duplicates: int = 0
    transport_errors: int = 0
    storage_errors: int = 0

    def snapshot(self) -> dict:
        return {"received": self.received, "admitted": self.admitted, "duplicates": self.duplicates, "transport_errors": self.transport_errors, "storage_errors": self.storage_errors}


@dataclass
class HerdrObservationAdapter:
    """Ingests observations; Core-owned correlation/projection remains separate."""

    transport: object
    store: ObservationStore
    generation: str
    health: TransportHealth = TransportHealth("healthy")
    subscription: object | None = None
    metrics: ObservationMetrics = field(default_factory=ObservationMetrics)

    def subscribe(self) -> ReadOnlySubscription:
        subscription = ReadOnlySubscription(self.transport, self._receive)
        try:
            self.transport.subscribe(self._receive)
        except TransportError as exc:
            self.metrics.transport_errors += 1
            self.health = TransportHealth("degraded", str(exc))
            raise
        self.health = TransportHealth("healthy", "subscribed")
        self.subscription = subscription
        return subscription

    def disable(self) -> None:
        """Stop observation only; preserve store and all Core-owned outcomes."""
        if self.subscription is not None and hasattr(self.subscription, "close"):
            self.subscription.close()
        self.health = TransportHealth("disabled", "observation ingestion disabled")

    def _receive(self, notification: dict) -> dict:
        params = notification.get("params") or notification.get("data") or {}
        pane_id = params.get("pane_id")
        pane = self.transport.request("pane.get", {"pane_id": pane_id})
        pane = pane.get("pane", pane)
        return self.ingest(notification, pane)

    def ingest(self, notification: dict, pane: dict) -> dict:
        """Normalize and durably admit one fake or protocol-22 event."""
        self.metrics.received += 1
        event = normalize(notification, pane, generation=self.generation)
        try:
            if self.store.receive(event):
                self.metrics.admitted += 1
            else:
                self.metrics.duplicates += 1
        except StoragePressureError as exc:
            self.metrics.storage_errors += 1
            self.health = TransportHealth("degraded", str(exc))
            raise
        return event

    def consume_stream_event(self, subscription, pane_id: str) -> dict:
        """Poll one persistent read-only stream event through the same pipeline."""
        try:
            notification = subscription.poll()
        except TransportError:
            self.metrics.transport_errors += 1
            raise
        pane = self.transport.request("pane.get", {"pane_id": pane_id})
        return self.ingest(notification, pane.get("pane", pane))

    def replay_pending(self) -> list[dict]:
        """Return committed observations awaiting authority-owned projection."""
        return self.store.pending()

    def correlate_and_project(
        self,
        event: dict,
        correlator: Correlator,
        *,
        request_id: str,
        in_reply_to: str,
        sequence: int,
    ) -> dict | None:
        """Project one admitted event through a Core-owned correlation registry.

        Herdr fields are converted to an observation only.  The correlator
        supplies the authoritative execution identity and status; suppressed
        or unattributed observations are durably dispositioned without an
        ``agent-runtime.v1`` result.
        """
        herdr_event = HerdrEvent(
            event_id=event["event_id"],
            herdr_state=event["herdr_state"],
            occurred_at=event["occurred_at"],
            source_seq=int(event.get("state_change_seq", 0)),
            agent_kind=event.get("agent_kind", ""),
            agent_name=event.get("agent_name", ""),
            agent_session_provider=(event.get("agent_session") or {}).get("provider", "") or "",
            agent_session_value=(event.get("agent_session") or {}).get("value", "") or "",
            pane_id=event.get("pane_id", ""),
            workspace_id=event.get("workspace_id", ""),
        )
        decision = correlator.ingest(herdr_event)
        self.store.record_disposition(event["event_id"], decision.kind, decision.detail)
        if decision.kind != "PROJECTED":
            return None
        envelope = project(decision, request_id=request_id, in_reply_to=in_reply_to, sequence=sequence)
        assert_envelope_shape(envelope)
        self.store.project_once(event["event_id"], envelope)
        return envelope
