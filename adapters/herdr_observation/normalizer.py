"""Normalize minimal Herdr notifications using an authoritative pane read."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

KNOWN_STATES = frozenset({"working", "blocked", "done", "idle", "unknown"})
PROVIDER_MAP = {"herdr:codex": "codex", "herdr:claude": "claude", "herdr:opencode": "opencode"}


def normalize(notification: dict, pane: dict, *, generation: str, received_at: str | None = None) -> dict:
    """Return a lossless, collision-safe observation; never invent execution identity."""
    params = notification.get("params")
    if notification.get("event") == "pane_agent_status_changed" and isinstance(notification.get("data"), dict):
        params = notification["data"]
    if not isinstance(params, dict) or (notification.get("method") not in {"pane.agent_status_changed", "pane_agent_status_changed"} and notification.get("event") != "pane_agent_status_changed"):
        raise ValueError("malformed Herdr status notification")
    pane_id = str(params.get("pane_id") or pane.get("pane_id") or "")
    state = params.get("state", params.get("agent_status", "unknown"))
    state = state if state in KNOWN_STATES else "unknown"
    seq = params.get("state_change_seq")
    session = pane.get("agent_session") or {}
    source = str(session.get("source") or "")
    value = str(session.get("value") or "")
    occurred = params.get("occurred_at") or pane.get("occurred_at")
    time_source = "upstream" if occurred else "adapter_receipt"
    occurred = occurred or received_at or datetime.now(timezone.utc).isoformat()
    identity_material = {
        "generation": generation,
        "pane": pane_id,
        "seq": seq,
        "state": state,
        "session_source": source,
        "session_value": value,
        "raw": notification,
    }
    event_id = "herdr-observation-" + sha256(json.dumps(identity_material, sort_keys=True, default=str).encode()).hexdigest()[:32]
    return {
        "event_id": event_id, "event_type": "observation.herdr.state_changed",
        "occurred_at": occurred, "occurred_at_source": time_source,
        "herdr_state": state, "pane_id": pane_id, "workspace_id": str(pane.get("workspace_id") or ""),
        "agent_kind": str(pane.get("agent_kind") or ""), "agent_name": str(pane.get("agent_name") or ""),
        "agent_session": {"source": source, "provider": PROVIDER_MAP.get(source), "value": value},
        "revision": pane.get("revision"), "state_change_seq": seq, "raw": notification,
    }
