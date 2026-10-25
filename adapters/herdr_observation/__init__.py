"""Herdr semantic lifecycle observation adapter and Phase 016 fixtures.

The transport, normalizer, and store form the initial Phase 017 offline seam;
the original pure correlation helpers remain available for fixture conformance.

- pure, deterministic, offline (no sockets, no daemon calls);
- consumes Herdr-shaped normalized events; emits agent-runtime.v1-shaped
  observe_events envelopes or buffers unattributed facts as evidence;
- never mutates Herdr, never prompts agents, never owns status/completion.
"""

from .correlation import (  # noqa: F401
    BLOCKED,
    DONE,
    IDLE,
    UNKNOWN,
    WORKING,
    CorrelationRegistry,
    Correlator,
    Decision,
    DecisionKind,
    ExecutionIdentity,
    ExecutionRecord,
    HerdrEvent,
)
from .projection import (  # noqa: F401
    OBSERVATION_EVENT_TYPE,
    assert_envelope_shape,
    project,
)
from .dsh_shim import translate_dsh_event  # noqa: F401
from .adapter import HerdrObservationAdapter, ObservationMetrics  # noqa: F401
from .cli_provider import HerdrCliSnapshotProvider  # noqa: F401
from .normalizer import normalize  # noqa: F401
from .store import BoundedObservationBuffer, ObservationStore, StoragePressureError  # noqa: F401
from .transport import (  # noqa: F401
    FakeHerdrProvider,
    HerdrEnvelope,
    ReadOnlySubscription,
    ReconnectBackoff,
    UnixSocketReadOnlyTransport,
    UnixSocketSubscription,
    ReconnectingAgentStatusStream,
    TransportHealth,
    READ_ONLY_METHODS,
    SUPPORTED_PROTOCOLS,
    TransportError,
    negotiate_protocol,
    reconcile_sequence,
    validate_read_only_method,
)

__all__ = [
    "BLOCKED", "DONE", "IDLE", "UNKNOWN", "WORKING",
    "CorrelationRegistry", "Correlator", "Decision", "DecisionKind",
    "ExecutionIdentity", "ExecutionRecord", "HerdrEvent",
    "OBSERVATION_EVENT_TYPE", "assert_envelope_shape", "project",
    "translate_dsh_event",
    "HerdrObservationAdapter",
    "ObservationMetrics",
    "HerdrCliSnapshotProvider",
    "normalize", "ObservationStore", "BoundedObservationBuffer", "StoragePressureError", "FakeHerdrProvider", "HerdrEnvelope", "ReadOnlySubscription",
    "READ_ONLY_METHODS", "SUPPORTED_PROTOCOLS", "TransportError", "TransportHealth", "ReconnectBackoff", "UnixSocketReadOnlyTransport", "UnixSocketSubscription", "ReconnectingAgentStatusStream", "negotiate_protocol", "reconcile_sequence", "validate_read_only_method",
]
