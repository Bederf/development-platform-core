"""Projection of correlated Herdr observations into agent-runtime.v1 shape.

Fixture logic only. Emits ``observe_events`` RESULT envelopes using the
frozen contract's existing surface (Gate 1: zero schema changes).

Authority invariants enforced here:
- ``status`` is echoed from the authority-owned registry record and can
  never originate from Herdr content (B2).
- ``payload`` carries the raw Herdr state verbatim; ``unknown`` survives.
- No artifacts, no Forge references, no completion semantics exist on this
  path (operator scenario 8).
"""

from __future__ import annotations

from dataclasses import asdict

from .correlation import Decision, DecisionKind

OBSERVATION_EVENT_TYPE = "observation.herdr.state_changed"

_ALLOWED_RESULT_KEYS = frozenset(
    {
        "schema",
        "message_type",
        "operation",
        "request_id",
        "in_reply_to",
        "execution",
        "status",
        "events",
    }
)


def project(decision: Decision, *, request_id: str, in_reply_to: str, sequence: int) -> dict:
    """Build an ``observe_events`` result envelope from a PROJECTED decision."""
    if decision.kind != DecisionKind.PROJECTED:
        raise ValueError("only PROJECTED decisions may be projected: %s" % decision.kind)
    record = decision.record
    if record is None:  # pragma: no cover - guarded by kind check
        raise ValueError("projected decision lacks execution record")
    event = decision.event
    return {
        "schema": "agent-runtime.v1",
        "message_type": "result",
        "operation": "observe_events",
        "request_id": request_id,
        "in_reply_to": in_reply_to,
        "execution": asdict(record.identity),
        "status": record.status,
        "events": [
            {
                "event_id": event.event_id,
                "event_type": OBSERVATION_EVENT_TYPE,
                "sequence": int(sequence),
                "occurred_at": event.occurred_at,
                "payload": {
                    "source": "herdr",
                    "herdr_state": event.herdr_state,
                    "agent_kind": event.agent_kind,
                    "agent_name": event.agent_name,
                    "pane_id": event.pane_id,
                    "workspace_id": event.workspace_id,
                    "provider_session": {
                        "provider": record.provider,
                        "session_id": record.provider_session_id,
                    },
                },
            }
        ],
    }


def assert_envelope_shape(envelope: dict) -> None:
    """Minimal frozen-conformance checks (no external deps).

    Mirrors the load-bearing requirements of
    ``contracts/agent-runtime.v1.schema.json`` for result envelopes.
    """
    extra = set(envelope) - _ALLOWED_RESULT_KEYS
    if extra:
        raise AssertionError("unexpected top-level keys: %s" % sorted(extra))
    if envelope["schema"] != "agent-runtime.v1":
        raise AssertionError("schema const violated")
    if envelope["message_type"] != "result":
        raise AssertionError("message_type must be result")
    if envelope["operation"] != "observe_events":
        raise AssertionError("operation must be observe_events")
    for key in ("request_id", "in_reply_to", "status"):
        if not isinstance(envelope[key], str) or not envelope[key]:
            raise AssertionError("%s must be a non-empty string" % key)
    execution = envelope["execution"]
    for key in (
        "control_plane_id",
        "work_item_id",
        "run_id",
        "execution_id",
        "attempt_id",
    ):
        value = execution.get(key)
        if not isinstance(value, str) or not value:
            raise AssertionError("execution.%s must be non-empty string" % key)
    for event in envelope["events"]:
        for key in ("event_id", "event_type", "sequence", "occurred_at"):
            if key not in event:
                raise AssertionError("event missing %s" % key)
        if not isinstance(event["sequence"], int) or event["sequence"] < 0:
            raise AssertionError("event.sequence must be integer >= 0")
