"""Deliberately thin DSH -> Herdr state-report shim (fixture level).

Translates DSH lifecycle events into Herdr ``pane.report_agent`` report
envelopes — push-based semantic state, per the audited integration-hook
mechanism, WITHOUT touching Herdr itself: no enum change, no plugin, no
installation. Output is a plain JSON-able dict; wiring it to a live socket
is later-stage work outside Gate 3.

Limitations recorded in the Gate-3 evidence:
- The DSH event-type vocabulary below is REPRESENTATIVE. Production wiring
  must confirm DSH's actual emitted event-type strings; unknown DSH events
  map to None (never guessed).
- Report field names mirror the audited integration assets structurally;
  byte-level upstream conformance is verified only when a live
  developer-mode check runs.
"""

from __future__ import annotations

from typing import Optional

# Representative mapping. Values are Herdr public states only.
DSH_EVENT_TO_HERDR_STATE = {
    "turn_started": "working",
    "model_request_started": "working",
    "tool_execution_started": "working",
    "awaiting_tool_approval": "blocked",
    "awaiting_user_approval": "blocked",
    "turn_completed": "idle",
}


def translate_dsh_event(
    dsh_event: dict, *, agent_name: str, pane_id: str, seq: int
) -> Optional[dict]:
    """Translate one DSH lifecycle event into a Herdr report envelope.

    Returns ``None`` for events with no Herdr-state meaning (including all
    unrecognized types): the shim never guesses.
    """
    event_type = dsh_event.get("event_type")
    state = DSH_EVENT_TO_HERDR_STATE.get(event_type)
    if state is None:
        return None
    return {
        "method": "pane.report_agent",
        "params": {
            "pane_id": pane_id,
            "agent": agent_name,
            "state": state,
            "seq": int(seq),
            "source": "dsh-hook",
        },
    }
