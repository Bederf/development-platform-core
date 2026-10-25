"""Bounded GSD-boundary checkpoint event producer.

The event is a derived handoff from a GSD/Radix boundary to the working-state
provider. It is not a session record, task authority, execution instruction,
or verification result.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


class CheckpointEventError(ValueError):
    """Raised when a checkpoint event request is unsafe or incomplete."""


_REASONS = {"startup", "transition", "handoff", "terminal"}
_SUMMARY_FIELDS = {"completed", "discoveries", "failures"}
_FORBIDDEN = {
    "authorization", "credentials", "execute", "policy_decision", "prompt",
    "raw_prompt", "raw_tool_output", "tool_arguments",
}
_MAX_ITEMS = 32
_MAX_LENGTH = 240


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class CheckpointEventProducer:
    """Produce a bounded, provider-neutral checkpoint event from authorities."""

    schema = "working-state-checkpoint-event.v1"

    def __init__(self, *, project_id: str) -> None:
        if not isinstance(project_id, str) or not project_id.strip():
            raise CheckpointEventError("project_id must be a non-empty string")
        self.project_id = project_id.strip()

    def produce(
        self,
        *,
        session_id: str,
        gsd: Mapping[str, Any],
        session_record_refs: Sequence[str],
        summaries: Mapping[str, Sequence[str]],
        reason: str,
    ) -> dict[str, Any]:
        if not isinstance(session_id, str) or not session_id.strip():
            raise CheckpointEventError("session_id must be a non-empty string")
        if reason not in _REASONS:
            raise CheckpointEventError("checkpoint boundary is not declared")
        self._require_gsd(gsd)
        refs = list(session_record_refs)
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise CheckpointEventError("session_record_refs must be non-empty strings")
        if len(refs) > _MAX_ITEMS or len(set(refs)) != len(refs):
            raise CheckpointEventError("session_record_refs are not bounded and unique")
        bounded = self._summaries(summaries)
        event: dict[str, Any] = {
            "schema": self.schema,
            "event_id": f"checkpoint-event:{self.project_id}:{session_id}",
            "project_id": self.project_id,
            "session_id": session_id,
            "gsd_ref": str(gsd["ref"]),
            "session_record_refs": refs,
            "source_digests": {"gsd": _digest(dict(gsd))},
            "objective": str(gsd["objective"]),
            "phase": gsd["phase"],
            "completed_summary": bounded["completed"],
            "discovery_summary": bounded["discoveries"],
            "failure_summary": bounded["failures"],
            "next_step": str(gsd["next"]),
            "blocker": str(gsd["blocker"]),
            "reason": reason,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        event["event_digest"] = _digest(event)
        return event

    @staticmethod
    def _require_gsd(gsd: Mapping[str, Any]) -> None:
        if not isinstance(gsd.get("ref"), str) or not gsd["ref"].strip():
            raise CheckpointEventError("gsd.ref is required")
        for field in ("objective", "phase", "next", "blocker"):
            if field not in gsd:
                raise CheckpointEventError(f"gsd.{field} is required")
        if any(key in gsd for key in _FORBIDDEN):
            raise CheckpointEventError("gsd contains forbidden authority material")

    @staticmethod
    def _summaries(values: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
        if set(values) - _SUMMARY_FIELDS or set(values) & _FORBIDDEN:
            raise CheckpointEventError("unsupported or forbidden summary field")
        result: dict[str, list[str]] = {}
        for field in _SUMMARY_FIELDS:
            items = list(values.get(field, []))
            if len(items) > _MAX_ITEMS or any(
                not isinstance(item, str) or not item.strip() or len(item) > _MAX_LENGTH
                for item in items
            ):
                raise CheckpointEventError(f"{field} summary is not bounded")
            result[field] = items
        return result


def validate_checkpoint_event(event: Mapping[str, Any], *, project_id: str) -> None:
    """Validate event integrity before handing it to a derived provider."""

    required = {
        "schema", "event_id", "project_id", "session_id", "gsd_ref", "session_record_refs",
        "source_digests", "objective", "phase", "completed_summary", "discovery_summary",
        "failure_summary", "next_step", "blocker", "reason", "occurred_at", "event_digest",
    }
    if set(event) != required:
        raise CheckpointEventError("checkpoint event fields are invalid")
    if event["schema"] != CheckpointEventProducer.schema or event["project_id"] != project_id:
        raise CheckpointEventError("checkpoint event is not bound to this project/schema")
    if event["reason"] not in _REASONS:
        raise CheckpointEventError("checkpoint event reason is invalid")
    CheckpointEventProducer._summaries({
        "completed": event["completed_summary"],
        "discoveries": event["discovery_summary"],
        "failures": event["failure_summary"],
    })
    if any(key in event for key in _FORBIDDEN):
        raise CheckpointEventError("checkpoint event contains forbidden authority material")
    unsigned = dict(event)
    actual = unsigned.pop("event_digest")
    if _digest(unsigned) != actual:
        raise CheckpointEventError("checkpoint event digest is invalid")
