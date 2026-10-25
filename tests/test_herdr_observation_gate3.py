"""Phase 016 Gate 3 fixtures — Herdr semantic correlation (synthetic).

Proves operator scenarios 1-8 entirely offline: no sockets, no daemon,
no Herdr modification. Every Herdr-shaped input mirrors structures
observed in live ``herdr api snapshot`` output (2026-08-25).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from adapters.herdr_observation import (
    BLOCKED,
    CorrelationRegistry,
    Correlator,
    DecisionKind,
    DONE,
    ExecutionIdentity,
    ExecutionRecord,
    IDLE,
    OBSERVATION_EVENT_TYPE,
    UNKNOWN,
    WORKING,
    project,
    translate_dsh_event,
)
from adapters.herdr_observation.projection import assert_envelope_shape


IDENTITY = ExecutionIdentity(
    control_plane_id="cp-1",
    work_item_id="wi-9",
    run_id="run-77",
    execution_id="exec-771",
    attempt_id="att-1",
)
OTHER_IDENTITY = ExecutionIdentity(
    control_plane_id="cp-2",
    work_item_id="wi-8",
    run_id="run-70",
    execution_id="exec-770",
    attempt_id="att-9",
)
AUTHORITY_STATUS = "RUNNING"


def make_correlator() -> Correlator:
    registry = CorrelationRegistry()
    registry.register(
        ExecutionRecord(
            identity=IDENTITY,
            provider="dsh",
            provider_session_id="dsess-123",
            status=AUTHORITY_STATUS,
            previous_attempt_ids=frozenset({"att-0"}),
        )
    )
    registry.register(
        ExecutionRecord(
            identity=OTHER_IDENTITY,
            provider="codex",
            provider_session_id="codex-abc",
            status=AUTHORITY_STATUS,
        )
    )
    return Correlator(registry=registry)


def herdr_event(**overrides):
    base = dict(
        event_id="ev-1",
        herdr_state=WORKING,
        occurred_at="2026-08-25T12:00:00Z",
        source_seq=100,
        agent_kind="dsh",
        agent_name="impl",
        agent_session_provider="dsh",
        agent_session_value="dsess-123",
        pane_id="w1:p2",
        workspace_id="w1",
    )
    base.update(overrides)
    return HerdrEventStub(**base)


from adapters.herdr_observation.correlation import HerdrEvent as HerdrEventStub


# ---------------------------------------------------------------------------
# Scenario 1 — attributed event joins via provider session id only
# ---------------------------------------------------------------------------

def test_scenario_1_attributed_event_projects_into_runtime_envelope():
    cor = make_correlator()
    d = cor.ingest(herdr_event())
    assert d.kind == DecisionKind.PROJECTED
    envelope = project(d, request_id="req-1", in_reply_to="req-0", sequence=0)
    assert_envelope_shape(envelope)
    assert envelope["operation"] == "observe_events"
    assert envelope["execution"] == {
        "control_plane_id": "cp-1",
        "work_item_id": "wi-9",
        "run_id": "run-77",
        "execution_id": "exec-771",
        "attempt_id": "att-1",
    }
    payload = envelope["events"][0]["payload"]
    assert payload["provider_session"] == {"provider": "dsh", "session_id": "dsess-123"}
    assert payload["herdr_state"] == WORKING


# ---------------------------------------------------------------------------
# Scenario 2 — unattributed event is buffered as evidence only
# ---------------------------------------------------------------------------

def test_scenario_2_unattributed_event_never_reaches_runtime_surface():
    cor = make_correlator()
    d = cor.ingest(herdr_event(event_id="ev-u1", agent_session_value="ghost-session"))
    assert d.kind == DecisionKind.UNATTRIBUTED
    assert len(cor.buffer) == 1
    assert cor.buffer[0]["reason"] == "unattributed_no_execution_identity"
    with pytest.raises(ValueError):
        project(d, request_id="r", in_reply_to="r", sequence=0)


# ---------------------------------------------------------------------------
# Scenario 3 — duplicate event deduplicated without lifecycle corruption
# ---------------------------------------------------------------------------

def test_scenario_3_duplicate_event_is_rejected_exactly_once():
    cor = make_correlator()
    first = cor.ingest(herdr_event(source_seq=100))
    again = cor.ingest(herdr_event(source_seq=100))
    assert first.kind == DecisionKind.PROJECTED
    assert again.kind == DecisionKind.DUPLICATE_REJECTED
    assert sum(1 for x in cor.decisions if x.kind == DecisionKind.PROJECTED) == 1


# ---------------------------------------------------------------------------
# Scenario 4 — stale events fenced by sequence and by superseded attempt
# ---------------------------------------------------------------------------

def test_scenario_4a_stale_sequence_rejected():
    cor = make_correlator()
    assert cor.ingest(herdr_event(event_id="a", source_seq=105)).kind == DecisionKind.PROJECTED
    late = cor.ingest(herdr_event(event_id="b", source_seq=104))
    assert late.kind == DecisionKind.STALE_SEQUENCE_REJECTED
    replayed = cor.ingest(herdr_event(event_id="c", source_seq=105))
    assert replayed.kind == DecisionKind.STALE_SEQUENCE_REJECTED


def test_scenario_4b_superseded_attempt_rejected_via_authority_lineage():
    cor = make_correlator()
    d = cor.ingest(
        herdr_event(event_id="old-attempt", claimed_attempt_id="att-0")
    )
    assert d.kind == DecisionKind.STALE_ATTEMPT_REJECTED
    fresh = cor.ingest(herdr_event(event_id="current-attempt", claimed_attempt_id="att-1"))
    assert fresh.kind == DecisionKind.PROJECTED


def test_scenario_4c_late_out_of_order_with_higher_sequence_is_accepted():
    cor = make_correlator()
    assert cor.ingest(herdr_event(event_id="x1", source_seq=200)).kind == DecisionKind.PROJECTED
    arrived_late = cor.ingest(herdr_event(event_id="x2", source_seq=260))
    assert arrived_late.kind == DecisionKind.PROJECTED


# ---------------------------------------------------------------------------
# Scenario 5 — unknown preserved; idle/done suppressed everywhere
# ---------------------------------------------------------------------------

def test_scenario_5_unknown_survives_verbatim_and_never_becomes_status():
    cor = make_correlator()
    d = cor.ingest(herdr_event(event_id="u", herdr_state=UNKNOWN))
    assert d.kind == DecisionKind.PROJECTED
    envelope = project(d, request_id="r", in_reply_to="r", sequence=3)
    assert envelope["events"][0]["payload"]["herdr_state"] == UNKNOWN
    assert envelope["status"] == AUTHORITY_STATUS  # echoed, never derived


@pytest.mark.parametrize("state", [IDLE, DONE])
def test_scenario_5_idle_and_done_yield_nothing(state):
    cor = make_correlator()
    d = cor.ingest(herdr_event(event_id="s-" + state, herdr_state=state))
    assert d.kind == DecisionKind.SUPPRESSED_STATE
    assert cor.buffer == []


# ---------------------------------------------------------------------------
# Scenario 6 — wrong provider session cannot attach to another execution
# ---------------------------------------------------------------------------

def test_scenario_6_forged_execution_claim_cannot_redirect_attachment():
    cor = make_correlator()
    d = cor.ingest(
        herdr_event(
            event_id="forged",
            agent_session_provider="dsh",
            agent_session_value="dsess-123",  # resolves to IDENTITY
            claimed_execution=OTHER_IDENTITY,  # attacker claims codex exec
        )
    )
    assert d.kind == DecisionKind.CROSS_EXECUTION_REJECTED
    assert d.record.identity == IDENTITY  # resolution unchanged


def test_scenario_6_foreign_provider_session_maps_only_to_its_own_execution():
    cor = make_correlator()
    d = cor.ingest(
        herdr_event(
            event_id="other",
            agent_kind="codex",
            agent_session_provider="codex",
            agent_session_value="codex-abc",
        )
    )
    assert d.kind == DecisionKind.PROJECTED
    assert d.record.identity.execution_id == OTHER_IDENTITY.execution_id


# ---------------------------------------------------------------------------
# Scenario 7 — DSH lifecycle states are observations, never authority
# ---------------------------------------------------------------------------

def test_scenario_7_dsh_blocked_translates_and_projects_as_observation_only():
    report = translate_dsh_event(
        {"event_type": "awaiting_tool_approval"},
        agent_name="impl",
        pane_id="w1:p2",
        seq=41,
    )
    assert report == {
        "method": "pane.report_agent",
        "params": {
            "pane_id": "w1:p2",
            "agent": "impl",
            "state": BLOCKED,
            "seq": 41,
            "source": "dsh-hook",
        },
    }
    cor = make_correlator()
    d = cor.ingest(
        herdr_event(event_id="blk", herdr_state=report["params"]["state"], source_seq=41)
    )
    envelope = project(d, request_id="rq", in_reply_to="rq0", sequence=7)
    assert_envelope_shape(envelope)
    assert envelope["events"][0]["payload"]["herdr_state"] == BLOCKED
    assert envelope["status"] == AUTHORITY_STATUS


def test_scenario_7_shim_never_guesses_unknown_dsh_events():
    assert translate_dsh_event({"event_type": "quantum_flux"}, agent_name="i", pane_id="p", seq=1) is None
    assert translate_dsh_event({}, agent_name="i", pane_id="p", seq=1) is None


def test_scenario_7_turn_completion_reports_idle_which_core_suppresses():
    report = translate_dsh_event(
        {"event_type": "turn_completed"}, agent_name="impl", pane_id="w1:p2", seq=42
    )
    assert report["params"]["state"] == IDLE
    cor = make_correlator()
    d = cor.ingest(
        herdr_event(event_id="fin", herdr_state=report["params"]["state"])
    )
    assert d.kind == DecisionKind.SUPPRESSED_STATE  # B2: done/idle yield nothing


# ---------------------------------------------------------------------------
# Scenario 8 — Herdr "done" never means Forge PASS or platform DONE
# ---------------------------------------------------------------------------

def test_scenario_8_no_artifacts_no_forge_no_completion_on_observation_path():
    cor = make_correlator()
    for i, state in enumerate([WORKING, BLOCKED, UNKNOWN]):
        d = cor.ingest(herdr_event(event_id="sc8-%d" % i, herdr_state=state, source_seq=300 + i))
        envelope = project(
            d, request_id="r8-%d" % i, in_reply_to="r8-%d" % i, sequence=i
        )
        assert_envelope_shape(envelope)
        assert "artifacts" not in envelope
        blob = repr(envelope)
        for forbidden in ("forge", "Forge", "SUCCEEDED", "verification_result"):
            assert forbidden not in blob


def test_scenario_8_status_is_always_the_authority_echo_across_all_states():
    cor = make_correlator()
    seq = 400
    for i, state in enumerate([WORKING, BLOCKED, UNKNOWN, IDLE, DONE]):
        d = cor.ingest(
            herdr_event(event_id="echo-%d" % i, herdr_state=state, source_seq=seq + i)
        )
        if d.kind == DecisionKind.SUPPRESSED_STATE:
            continue
        envelope = project(d, request_id="e%d" % i, in_reply_to="e%d" % i, sequence=i)
        assert envelope["status"] == AUTHORITY_STATUS


def test_event_type_vocabulary_is_namespaced_observation():
    assert OBSERVATION_EVENT_TYPE == "observation.herdr.state_changed"
