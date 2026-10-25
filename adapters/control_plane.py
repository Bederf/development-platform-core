"""Provider-neutral control-plane projection harness for Phase 011.

This is deliberately not a Herdr transport.  It models the narrow boundary a
control-plane adapter must preserve before a real platform integration exists.
External providers are represented as plain event mappings so this module does
not import or depend on any candidate control-plane implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


REQUIRED_IDENTITIES = (
    "event_id",
    "correlation_id",
    "control_plane_id",
    "work_item_id",
    "agent_id",
    "execution_id",
    "attempt_id",
    "timestamp",
    "event_type",
)


class InvalidControlPlaneEvent(ValueError):
    """Raised when an external event cannot be safely correlated."""


@dataclass(frozen=True)
class PlatformEvent:
    """Lossless, validated representation of one external transition."""

    event_id: str
    correlation_id: str
    control_plane_id: str
    work_item_id: str
    agent_id: str
    execution_id: str
    attempt_id: str
    timestamp: str
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionProjection:
    """Authoritative-looking projection used only by this conformance harness."""

    work_item_id: str
    attempts: dict[str, list[str]] = field(default_factory=dict)
    artifacts: set[str] = field(default_factory=set)
    forge_status: str | None = None
    completion_authorized: bool = False
    failure_reasons: list[str] = field(default_factory=list)


class ControlPlaneProjection:
    """Translate external events without granting them platform authority."""

    def __init__(self) -> None:
        self.events: dict[str, PlatformEvent] = {}
        self.executions: dict[str, ExecutionProjection] = {}

    def ingest(self, raw_event: Mapping[str, Any]) -> str:
        missing = [
            identity
            for identity in REQUIRED_IDENTITIES
            if not isinstance(raw_event.get(identity), str) or not raw_event[identity]
        ]
        if missing:
            raise InvalidControlPlaneEvent(f"missing identities: {', '.join(missing)}")

        event_id = raw_event["event_id"]
        if event_id in self.events:
            return "duplicate"

        event = PlatformEvent(
            **{identity: raw_event[identity] for identity in REQUIRED_IDENTITIES},
            payload=dict(raw_event.get("payload") or {}),
        )
        self.events[event.event_id] = event
        projection = self.executions.setdefault(
            event.execution_id, ExecutionProjection(event.work_item_id)
        )
        if projection.work_item_id != event.work_item_id:
            raise InvalidControlPlaneEvent("execution mapped to multiple work items")

        if event.event_type == "attempt_started":
            projection.attempts.setdefault(event.attempt_id, []).append(event.event_id)
        elif event.event_type == "artifact_produced":
            artifact_id = event.payload.get("artifact_id")
            if isinstance(artifact_id, str) and artifact_id:
                projection.artifacts.add(artifact_id)
        elif event.event_type == "forge_verification":
            status = event.payload.get("status")
            if status not in {"PASSED", "FAILED"}:
                raise InvalidControlPlaneEvent("Forge status must be PASSED or FAILED")
            projection.forge_status = status
            if status == "FAILED":
                projection.failure_reasons.append("forge_failed")
            projection.completion_authorized = status == "PASSED" and bool(projection.artifacts)
        elif event.event_type == "control_plane_done":
            # External completion is observed, never trusted as authorization.
            projection.completion_authorized = projection.completion_authorized
        elif event.event_type == "execution_failed":
            reason = event.payload.get("reason")
            if isinstance(reason, str) and reason:
                projection.failure_reasons.append(reason)

        return "accepted"


class FakeControlPlaneProvider:
    """Candidate-independent event source used for adapter conformance tests."""

    def __init__(self) -> None:
        self._sequence = 0

    def event(self, event_type: str, **payload: Any) -> dict[str, Any]:
        self._sequence += 1
        return {
            "event_id": f"event-{self._sequence}",
            "correlation_id": "correlation-001",
            "control_plane_id": "cp-task-001",
            "work_item_id": "work-001",
            "agent_id": "agent-codex",
            "execution_id": "execution-001",
            "attempt_id": "attempt-001",
            "timestamp": "2026-08-15T00:00:00Z",
            "event_type": event_type,
            "payload": payload,
        }
