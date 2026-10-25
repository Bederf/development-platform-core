"""Herdr observation correlation and lineage fencing (fixture logic).

Implements the Gate-1 binding interpretations over synthetic streams:

- B1: executions are resolved EXCLUSIVELY through the authority-owned
  registry join ``(provider, provider_session_id) -> execution``. The
  adapter never mints identity, and caller-supplied execution claims can
  never redirect attachment.
- B2: ``idle``/``done`` are suppressed pre-attribution; ``unknown``
  survives verbatim; nothing here produces status or completion.
- B4: unattributed observations land in an evidence-only buffer.

Fencing follows the Phase-013 lineage pattern: duplicate event ids are
rejected once-seen; per-execution sequence high-water rejects stale
replays/out-of-order replays; superseded attempts (authority-declared
``previous_attempt_ids``) reject stale-attempt attachments.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


WORKING = "working"
BLOCKED = "blocked"
DONE = "done"
IDLE = "idle"
UNKNOWN = "unknown"

PROJECTABLE_STATES = frozenset({WORKING, BLOCKED, UNKNOWN})
SUPPRESSED_STATES = frozenset({IDLE, DONE})


class DecisionKind:
    PROJECTED = "PROJECTED"
    SUPPRESSED_STATE = "SUPPRESSED_STATE"
    UNATTRIBUTED = "UNATTRIBUTED"
    DUPLICATE_REJECTED = "DUPLICATE_REJECTED"
    STALE_SEQUENCE_REJECTED = "STALE_SEQUENCE_REJECTED"
    STALE_ATTEMPT_REJECTED = "STALE_ATTEMPT_REJECTED"
    CROSS_EXECUTION_REJECTED = "CROSS_EXECUTION_REJECTED"


@dataclass(frozen=True)
class ExecutionIdentity:
    control_plane_id: str
    work_item_id: str
    run_id: str
    execution_id: str
    attempt_id: str


@dataclass(frozen=True)
class ExecutionRecord:
    """Authority-owned binding of a platform execution to a provider session."""

    identity: ExecutionIdentity
    provider: str
    provider_session_id: str
    status: str
    previous_attempt_ids: frozenset = frozenset()

    @property
    def provider_session_key(self):
        return (self.provider, self.provider_session_id)


@dataclass
class CorrelationRegistry:
    records: dict = field(default_factory=dict)

    def register(self, record: ExecutionRecord) -> None:
        self.records[record.provider_session_key] = record

    def resolve(self, provider: str, session_id: str) -> Optional[ExecutionRecord]:
        if not provider or not session_id:
            return None
        return self.records.get((provider, session_id))


@dataclass(frozen=True)
class HerdrEvent:
    """Normalized Herdr observation (shape mirrors live api snapshot fields)."""

    event_id: str
    herdr_state: str
    occurred_at: str
    source_seq: int = 0
    agent_kind: str = ""
    agent_name: str = ""
    agent_session_provider: str = ""
    agent_session_value: str = ""
    pane_id: str = ""
    workspace_id: str = ""
    claimed_execution: Optional[ExecutionIdentity] = None
    claimed_attempt_id: Optional[str] = None


@dataclass(frozen=True)
class Decision:
    kind: str
    event: HerdrEvent
    detail: str = ""
    record: Optional[ExecutionRecord] = None


@dataclass
class Correlator:
    registry: CorrelationRegistry
    decisions: list = field(default_factory=list)
    buffer: list = field(default_factory=list)
    _seen_event_ids: set = field(default_factory=set)
    _sequence_high_water: dict = field(default_factory=dict)

    def ingest(self, event: HerdrEvent) -> Decision:
        # 1. Duplicate fencing (once-seen, regardless of later disposition).
        if event.event_id in self._seen_event_ids:
            return self._decide(
                Decision(kind=DecisionKind.DUPLICATE_REJECTED, event=event,
                         detail="event_id already processed")
            )
        self._seen_event_ids.add(event.event_id)

        # 2. State suppression BEFORE attribution (B2): idle/done yield nothing.
        if event.herdr_state in SUPPRESSED_STATES:
            return self._decide(
                Decision(kind=DecisionKind.SUPPRESSED_STATE, event=event,
                         detail="state %r yields no observation" % event.herdr_state)
            )
        if event.herdr_state not in PROJECTABLE_STATES:
            return self._decide(
                Decision(kind=DecisionKind.UNATTRIBUTED, event=event,
                         detail="unclassifiable herdr state preserved verbatim")
            )

        # 3. Attribution exclusively via the authority-owned join (B1).
        record = self.registry.resolve(
            event.agent_session_provider, event.agent_session_value
        )
        if record is None:
            self.buffer.append(
                {
                    "event": asdict(event),
                    "reason": "unattributed_no_execution_identity",
                    "occurred_at": event.occurred_at,
                }
            )
            return self._decide(
                Decision(kind=DecisionKind.UNATTRIBUTED, event=event,
                         detail="no registry entry for provider session")
            )

        # 4. Cross-execution guard: a supplied execution claim can never win.
        if (
            event.claimed_execution is not None
            and event.claimed_execution != record.identity
        ):
            return self._decide(
                Decision(kind=DecisionKind.CROSS_EXECUTION_REJECTED, event=event,
                         record=record,
                         detail="claimed execution contradicts registry resolution")
            )

        # 5. Attempt-lineage fencing against authority-declared history.
        if event.claimed_attempt_id is not None:
            allowed = {record.identity.attempt_id} | set(record.previous_attempt_ids)
            if event.claimed_attempt_id not in allowed:
                return self._decide(
                    Decision(kind=DecisionKind.STALE_ATTEMPT_REJECTED, event=event,
                             record=record,
                             detail="attempt outside authority lineage")
                )
            if event.claimed_attempt_id in record.previous_attempt_ids:
                return self._decide(
                    Decision(kind=DecisionKind.STALE_ATTEMPT_REJECTED, event=event,
                             record=record,
                             detail="superseded attempt")
                )

        # 6. Sequence fencing per execution (stale replay / out-of-order replay).
        high = self._sequence_high_water.get(record.identity.execution_id)
        if high is not None and event.source_seq <= high:
            return self._decide(
                Decision(kind=DecisionKind.STALE_SEQUENCE_REJECTED, event=event,
                         record=record,
                         detail="source_seq %r <= high-water %r"
                                % (event.source_seq, high))
            )
        self._sequence_high_water[record.identity.execution_id] = event.source_seq

        return self._decide(
            Decision(kind=DecisionKind.PROJECTED, event=event, record=record,
                     detail="attributed observation")
        )

    def _decide(self, decision: Decision) -> Decision:
        self.decisions.append(decision)
        return decision
