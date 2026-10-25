"""Consumer-neutral construction of ``gsd-planning-lifecycle.v1`` records."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping


class GsdLifecycleError(ValueError):
    """Raised when a lifecycle record cannot be represented safely."""


class GsdLifecycleAdapter:
    """Build and append typed lifecycle events without owning phase authority."""

    _STATUSES = frozenset({"PROPOSED", "AUTHORIZED", "IN_PROGRESS", "VERIFICATION", "COMPLETE", "BLOCKED", "CANCELLED"})
    _EVENTS = frozenset({"STARTED", "DISPATCHED", "EXECUTED", "VERIFIED", "GOVERNED", "RECORDED", "COMPLETED", "BLOCKED"})

    def create(self, *, phase_id: str, phase_status: str, lifecycle_events: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        self._required(phase_id, "phase_id")
        if phase_status not in self._STATUSES:
            raise GsdLifecycleError(f"unsupported phase status: {phase_status!r}")
        events = [self._event(event) for event in (lifecycle_events or [])]
        return {"schema": "gsd-planning-lifecycle.v1", "phase_id": phase_id, "phase_status": phase_status, "lifecycle_events": events}

    def append(self, record: Mapping[str, Any], *, event: str, evidence_ref: str | None = None, occurred_at: str | None = None) -> dict[str, Any]:
        if not isinstance(record, Mapping) or record.get("schema") != "gsd-planning-lifecycle.v1":
            raise GsdLifecycleError("record must use gsd-planning-lifecycle.v1")
        result = deepcopy(dict(record))
        result["lifecycle_events"] = [self._event(item) for item in result.get("lifecycle_events", [])]
        result["lifecycle_events"].append(self._event({"event": event, "occurred_at": occurred_at or self._now(), "evidence_ref": evidence_ref}))
        return result

    def _event(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or value.get("event") not in self._EVENTS:
            raise GsdLifecycleError(f"unsupported lifecycle event: {value.get('event') if isinstance(value, Mapping) else None!r}")
        occurred_at = value.get("occurred_at")
        self._required(occurred_at, "occurred_at")
        evidence_ref = value.get("evidence_ref")
        if evidence_ref is not None and not isinstance(evidence_ref, str):
            raise GsdLifecycleError("evidence_ref must be null or a string")
        return {"event": str(value["event"]), "occurred_at": str(occurred_at), "evidence_ref": evidence_ref}

    @staticmethod
    def _required(value: Any, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise GsdLifecycleError(f"{name} must be a non-empty string")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
