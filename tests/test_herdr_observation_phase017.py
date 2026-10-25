from adapters.herdr_observation import (
    BoundedObservationBuffer, FakeHerdrProvider, HerdrCliSnapshotProvider, HerdrObservationAdapter, ObservationStore, ReadOnlySubscription, TransportError, normalize,
    CorrelationRegistry, Correlator, DecisionKind, ExecutionIdentity, ExecutionRecord, HerdrEvent, ReconnectBackoff, ReconnectingAgentStatusStream, StoragePressureError, UnixSocketReadOnlyTransport, negotiate_protocol,
    reconcile_sequence, validate_read_only_method,
)
from pathlib import Path


def pane(source="herdr:codex"):
    return {"pane_id": "p1", "workspace_id": "w1", "agent_kind": "cli", "agent_name": "codex", "agent_session": {"source": source, "value": "s1"}, "revision": 4}


def notification(state="working", seq=1):
    return {"method": "pane.agent_status_changed", "params": {"pane_id": "p1", "state": state, "state_change_seq": seq, "occurred_at": "2026-09-14T10:00:00Z"}}


def test_fake_provider_is_protocol_checked_and_read_only():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    assert provider.request("pane.get", {"pane_id": "p1"})["pane_id"] == "p1"
    for method in ("pane.create", "pane.input", "pane.report_agent", "server.stop"):
        try:
            validate_read_only_method(method)
        except TransportError:
            pass
        else:
            raise AssertionError(method)


def test_normalizer_preserves_states_unknown_and_provider_mapping():
    event = normalize(notification("done"), pane(), generation="g1")
    assert event["herdr_state"] == "done"
    assert event["agent_session"]["provider"] == "codex"
    unknown = normalize(notification("future_state", 2), pane("herdr:new"), generation="g1")
    assert unknown["herdr_state"] == "unknown"
    assert unknown["agent_session"]["provider"] is None


def test_identity_changes_across_generation_and_seq_reset():
    first = normalize(notification(seq=1), pane(), generation="g1")
    second = normalize(notification(seq=1), pane(), generation="g2")
    assert first["event_id"] != second["event_id"]


def test_identity_changes_across_provider_sessions_with_same_value():
    first = normalize(notification(seq=1), pane("herdr:codex"), generation="g1")
    second = normalize(notification(seq=1), pane("herdr:claude"), generation="g1")
    assert first["agent_session"]["value"] == second["agent_session"]["value"]
    assert first["event_id"] != second["event_id"]


def test_store_admits_and_projects_each_event_once():
    store = ObservationStore()
    event = normalize(notification(), pane(), generation="g1")
    result = {"event_id": event["event_id"], "status": "RUNNING"}
    assert store.receive(event) is True
    assert store.receive(event) is False
    assert store.project_once(event["event_id"], result) is True
    assert store.project_once(event["event_id"], result) is False
    assert store.pending() == []


def test_fake_provider_rejects_malformed_messages_and_resubscribes_after_loss():
    provider = FakeHerdrProvider()
    for message in ({}, {"method": "pane.create", "params": {}}, {"method": "pane.agent_status_changed", "params": "bad"}):
        try:
            provider.emit(message)
        except TransportError:
            pass
        else:
            raise AssertionError(message)
    seen = []
    subscription = ReadOnlySubscription(provider, seen.append)
    provider.subscribe(seen.append)
    provider.disconnect()
    subscription.reconnect()
    provider.emit(notification())
    assert provider.subscription_count == 2
    assert len(seen) == 1


def test_store_checkpoint_is_monotonic_and_buffer_eviction_is_deterministic():
    store = ObservationStore()
    store.checkpoint("herdr", 4)
    store.checkpoint("herdr", 2)
    assert store.high_water("herdr") == 4
    buffer = BoundedObservationBuffer(max_count=2, max_bytes=10000)
    for index in range(3):
        buffer.append({"event_id": f"e{index}", "payload": index})
    assert len(buffer) == 2
    assert buffer.evictions[0].event_id == "e0"


def test_receipt_and_unattributed_fact_survive_store_reopen(tmp_path: Path):
    path = str(tmp_path / "herdr.sqlite")
    event = normalize(notification(), pane(), generation="g1")
    first = ObservationStore(path)
    assert first.receive(event) is True
    assert first.record_unattributed(event, "no_execution_identity") is True
    first.db.close()  # crash boundary: receipt committed, projection never ran

    second = ObservationStore(path)
    assert [item["event_id"] for item in second.pending()] == [event["event_id"]]
    assert len(second.unattributed()) == 1
    assert second.project_once(event["event_id"], {"event_id": event["event_id"]}) is True
    second.db.close()

    third = ObservationStore(path)
    assert third.project_once(event["event_id"], {"event_id": event["event_id"]}) is False


def test_store_rolls_back_faults_at_receipt_and_projection_boundaries(monkeypatch):
    store = ObservationStore()
    event = normalize(notification(), pane(), generation="fault-boundary")

    def fail_trim(*args, **kwargs):
        raise RuntimeError("injected boundary fault")

    monkeypatch.setattr(store, "_trim_table", fail_trim)
    try:
        store.receive(event)
    except RuntimeError:
        pass
    else:
        raise AssertionError("receipt fault was not raised")
    assert store.pending() == []

    monkeypatch.undo()
    assert store.receive(event) is True
    monkeypatch.setattr(store, "_trim_table", fail_trim)
    try:
        store.project_once(event["event_id"], {"event_id": event["event_id"]})
    except RuntimeError:
        pass
    else:
        raise AssertionError("projection fault was not raised")
    assert store.pending() == [event]
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0

    monkeypatch.undo()
    assert store.project_once(event["event_id"], {"event_id": event["event_id"]}) is True
    assert store.project_once(event["event_id"], {"event_id": event["event_id"]}) is False


def test_storage_pressure_fails_closed_and_reports_degraded_health(monkeypatch):
    store = ObservationStore()
    event = normalize(notification(), pane(), generation="storage-pressure")

    def fail_trim(*args, **kwargs):
        import sqlite3
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(store, "_trim_table", fail_trim)
    try:
        store.receive(event)
    except StoragePressureError:
        pass
    else:
        raise AssertionError("storage pressure was not translated")
    assert store.pending() == []

    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    adapter = HerdrObservationAdapter(provider, store, "storage-pressure")
    adapter.subscribe()
    try:
        provider.emit(notification())
    except StoragePressureError:
        pass
    else:
        raise AssertionError("adapter did not fail closed on storage pressure")
    assert adapter.health.state == "degraded"
    assert adapter.metrics.storage_errors == 1


def test_checkpoint_rolls_back_when_crash_is_injected_before_commit(monkeypatch):
    from contextlib import contextmanager

    store = ObservationStore()

    @contextmanager
    def crash_after_write():
        with store.db:
            yield
            raise RuntimeError("injected pre-commit crash")

    monkeypatch.setattr(store, "_transaction", crash_after_write)
    try:
        store.checkpoint("herdr", 42)
    except RuntimeError:
        pass
    else:
        raise AssertionError("checkpoint crash was not raised")
    assert store.high_water("herdr") is None

    monkeypatch.undo()
    store.checkpoint("herdr", 42)
    assert store.high_water("herdr") == 42


def test_live_qualification_harness_is_bounded_and_machine_readable(monkeypatch):
    from scripts import herdr_observation_live_preflight as probe

    class SnapshotProvider:
        def snapshot(self):
            return {
                "protocol": 22,
                "version": "0.9.0",
                "agents": [{"pane_id": "w:p", "agent_session": {"source": "herdr:codex"}, "revision": 2, "state_change_seq": 3}],
            }

    class Stream:
        subscription = None
        health = type("Health", (), {"state": "healthy"})()

        def __init__(self, transport, pane_id):
            assert pane_id == "w:p"

        def connect(self):
            return None

        def poll(self):
            raise TransportError("timed out waiting for Herdr subscription event")

    monkeypatch.setattr(probe, "HerdrCliSnapshotProvider", SnapshotProvider)
    monkeypatch.setattr(probe, "ReconnectingAgentStatusStream", Stream)
    result = probe.qualify("/tmp/unused-herdr.sock", 0.01)
    assert result["subscription_health"] == "healthy"
    assert result["poll"]["outcome"] == "bounded_timeout"
    assert result["closed"] is True

    class EventStream(Stream):
        def poll(self):
            return {"event": "pane_agent_status_changed", "data": {"pane_id": "w:p", "agent_status": "working"}}

    monkeypatch.setattr(probe, "ReconnectingAgentStatusStream", EventStream)
    result = probe.qualify("/tmp/unused-herdr.sock", 0.01)
    assert result["poll"] == {
        "outcome": "event_received",
        "event": "pane_agent_status_changed",
        "pane_id": "w:p",
        "agent_status": "working",
    }


def test_reconciliation_detects_gaps_but_accepts_generation_reset():
    assert reconcile_sequence(4, 5)["state"] == "continuous"
    assert reconcile_sequence(4, 7) == {"state": "reconcile", "gap": True, "reason": "sequence_gap"}
    assert reconcile_sequence(20, 1, generation_changed=True)["reason"] == "unknown_or_new_generation"


def test_failed_reconnect_is_degraded_and_successful_resubscribe_recovers():
    provider = FakeHerdrProvider()
    subscription = ReadOnlySubscription(provider, lambda _: None)
    provider.disconnect()
    provider.protocol = 19
    try:
        subscription.reconnect()
    except TransportError:
        pass
    else:
        raise AssertionError("expected disconnected provider failure")
    assert subscription.health.state == "degraded"
    provider.protocol = 20
    subscription.reconnect()
    assert subscription.health.state == "healthy"


def test_composed_adapter_ingests_snapshot_enriched_observation_without_authority():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    store = ObservationStore()
    adapter = HerdrObservationAdapter(provider, store, "generation-1")
    adapter.subscribe()
    provider.emit(notification("blocked"))
    pending = adapter.replay_pending()
    assert len(pending) == 1
    assert pending[0]["herdr_state"] == "blocked"
    assert "execution_id" not in pending[0]
    assert adapter.health.state == "healthy"


def test_composed_adapter_deduplicates_replayed_delivery():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    store = ObservationStore()
    adapter = HerdrObservationAdapter(provider, store, "generation-1")
    adapter.subscribe()
    event = notification("working", 8)
    provider.emit(event)
    provider.emit(event)
    assert len(adapter.replay_pending()) == 1


def test_herdr_done_is_retained_as_observation_but_cannot_be_completion():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    store = ObservationStore()
    adapter = HerdrObservationAdapter(provider, store, "generation-1")
    adapter.subscribe()
    provider.emit(notification("done", 9))
    pending = adapter.replay_pending()[0]
    assert pending["herdr_state"] == "done"
    assert "status" not in pending
    assert "completion" not in pending
    assert "forge" not in pending


def test_authority_divergence_done_does_not_override_core_failed_outcome():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    store = ObservationStore()
    adapter = HerdrObservationAdapter(provider, store, "generation-1")
    adapter.subscribe()
    provider.emit(notification("done", 10))
    observed = adapter.replay_pending()[0]
    identity = ExecutionIdentity("cp", "wi", "run", "exec", "attempt")
    record = ExecutionRecord(identity, "codex", "s1", "FAILED")
    registry = CorrelationRegistry()
    registry.register(record)
    decision = Correlator(registry).ingest(HerdrEvent(
        event_id=observed["event_id"], herdr_state=observed["herdr_state"],
        occurred_at=observed["occurred_at"], source_seq=10,
        agent_session_provider="codex", agent_session_value="s1",
    ))
    assert decision.kind == DecisionKind.SUPPRESSED_STATE
    assert record.status == "FAILED"


def test_provider_free_forge_fail_divergence_keeps_herdr_done_non_authoritative(tmp_path: Path):
    from adapters.verification_lifecycle import ForgeResult, VerificationLifecycle

    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    adapter = HerdrObservationAdapter(provider, ObservationStore(), "forge-divergence")
    adapter.subscribe()
    provider.emit(notification("done", 11))
    observed = adapter.replay_pending()[0]
    identity = ExecutionIdentity("cp", "wi", "run", "exec", "attempt")
    record = ExecutionRecord(identity, "codex", "s1", "SUCCEEDED")
    registry = CorrelationRegistry()
    registry.register(record)
    decision = Correlator(registry).ingest(HerdrEvent(
        event_id=observed["event_id"], herdr_state="done", occurred_at=observed["occurred_at"],
        source_seq=11, agent_session_provider="codex", agent_session_value="s1",
    ))
    lifecycle = VerificationLifecycle(tmp_path)
    attempt = lifecycle.create_attempt(
        gsd_session_id="run", forge_session_id="forge", execution_id="exec",
        attempt_id="attempt", repository="core", baseline="base", lineage=("root",),
    )
    lifecycle.transition(attempt.identity.verification_attempt_id, "VERIFICATION_PENDING", "requested")
    running = lifecycle.transition(attempt.identity.verification_attempt_id, "FORGE_RUNNING", "started")
    result = ForgeResult(
        status="FAIL", evidence={"check": "required verification failed"},
        verification_attempt_id=running.identity.verification_attempt_id,
        gsd_session_id="run", forge_session_id="forge", execution_id="exec",
        attempt_id="attempt", repository="core", baseline="base", lineage=("root",),
    )
    failed, accepted = lifecycle.apply_result(result)
    assert decision.kind == DecisionKind.SUPPRESSED_STATE
    assert accepted is True
    assert failed.state == "VERIFICATION_FAILED"
    assert record.status == "SUCCEEDED"


def test_reconnect_backoff_is_bounded_and_jittered():
    backoff = ReconnectBackoff(base_seconds=1, max_seconds=4, jitter_ratio=0.25)
    assert backoff.delay(1, random_value=0) == 0.75
    assert backoff.delay(3, random_value=1) == 4
    assert backoff.delay(10, random_value=0.5) <= 4


def test_protocol_negotiation_accepts_reference_and_current_protocols_but_fails_closed():
    assert negotiate_protocol(20) == 20
    assert negotiate_protocol(22) == 22
    try:
        negotiate_protocol(99)
    except TransportError:
        pass
    else:
        raise AssertionError("unknown protocol was accepted")


def test_cli_snapshot_provider_is_read_only_and_protocol_checked(monkeypatch):
    response = '{"result":{"snapshot":{"protocol":22,"panes":[{"pane_id":"p1"}]}}}'
    class Completed:
        stdout = response
    provider = HerdrCliSnapshotProvider(runner=lambda *args, **kwargs: Completed())
    monkeypatch.setenv("HERDR_ENV", "1")
    assert provider.pane("p1")["pane_id"] == "p1"


def test_unix_transport_exposes_only_observation_methods():
    transport = UnixSocketReadOnlyTransport("/nonexistent")
    for method in ("pane.create", "pane.input", "agent.prompt", "server.stop"):
        try:
            transport.request(method)
        except TransportError:
            pass
        else:
            raise AssertionError(method)


def test_production_transport_static_surface_is_read_only():
    import inspect
    from adapters.herdr_observation import transport

    assert transport.READ_ONLY_METHODS == {
        "api.snapshot", "session.snapshot", "pane.get", "events.subscribe", "events.wait"
    }
    source = inspect.getsource(transport.UnixSocketReadOnlyTransport)
    for forbidden in ("pane.create", "pane.input", "pane.report_agent", "agent.prompt", "server.stop", "server.reload"):
        assert forbidden not in source


def test_normalizer_accepts_protocol_22_subscription_event_envelope():
    event = normalize(
        {"event": "pane_agent_status_changed", "data": {"pane_id": "p1", "agent_status": "working", "agent": "codex"}},
        pane(), generation="g2", received_at="2026-09-14T12:00:00Z",
    )
    assert event["herdr_state"] == "working"
    assert event["occurred_at_source"] == "adapter_receipt"


def test_normalizer_accepts_full_protocol_22_lifecycle_event_schema():
    event = normalize(
        {
            "event": "pane_agent_status_changed",
            "data": {
                "type": "pane_agent_status_changed",
                "pane_id": "p1",
                "workspace_id": "w1",
                "agent_status": "blocked",
                "agent": "codex",
                "display_agent": "codex",
                "state_labels": {"blocked": "needs input"},
                "title": "blocked",
            },
        },
        pane(),
        generation="schema-v22",
        received_at="2026-09-14T12:00:00Z",
    )
    assert event["herdr_state"] == "blocked"
    assert event["pane_id"] == "p1"
    assert event["workspace_id"] == "w1"
    assert event["occurred_at_source"] == "adapter_receipt"


def test_composed_adapter_consumes_protocol_22_stream_event_shape():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    adapter = HerdrObservationAdapter(provider, ObservationStore(), "g22")
    event = adapter.ingest(
        {"event": "pane_agent_status_changed", "data": {"pane_id": "p1", "agent_status": "working"}},
        pane(),
    )
    assert event["herdr_state"] == "working"
    assert len(adapter.replay_pending()) == 1


def test_adapter_projects_only_after_authority_owned_correlation():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    store = ObservationStore()
    adapter = HerdrObservationAdapter(provider, store, "projection")
    event = adapter.ingest(notification("working", 12), pane())
    identity = ExecutionIdentity("cp", "wi", "run", "exec", "attempt")
    record = ExecutionRecord(identity, "codex", "s1", "RUNNING")
    registry = CorrelationRegistry()
    registry.register(record)
    envelope = adapter.correlate_and_project(
        event, Correlator(registry), request_id="req-1", in_reply_to="req-0", sequence=0
    )
    assert envelope["operation"] == "observe_events"
    assert envelope["execution"]["execution_id"] == "exec"
    assert envelope["status"] == "RUNNING"
    assert store.disposition(event["event_id"])[0] == "PROJECTED"
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1


def test_adapter_does_not_project_suppressed_herdr_done():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    store = ObservationStore()
    adapter = HerdrObservationAdapter(provider, store, "suppressed-projection")
    event = adapter.ingest(notification("done", 13), pane())
    identity = ExecutionIdentity("cp", "wi", "run", "exec", "attempt")
    registry = CorrelationRegistry()
    registry.register(ExecutionRecord(identity, "codex", "s1", "SUCCEEDED"))
    assert adapter.correlate_and_project(
        event, Correlator(registry), request_id="req-2", in_reply_to="req-1", sequence=0
    ) is None
    assert store.disposition(event["event_id"])[0] == "SUPPRESSED_STATE"
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0


def test_disable_stops_observation_without_deleting_durable_state():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    store = ObservationStore()
    adapter = HerdrObservationAdapter(provider, store, "g-disable")
    adapter.subscribe()
    provider.emit(notification("working"))
    adapter.disable()
    assert adapter.health.state == "disabled"
    assert len(store.pending()) == 1
    assert provider.subscribers == []


def test_adapter_metrics_distinguish_admission_from_duplicate_delivery():
    provider = FakeHerdrProvider(snapshots={"p1": pane()})
    adapter = HerdrObservationAdapter(provider, ObservationStore(), "metrics")
    adapter.subscribe()
    message = notification()
    provider.emit(message)
    provider.emit(message)
    assert adapter.metrics.snapshot() == {"received": 2, "admitted": 1, "duplicates": 1, "transport_errors": 0, "storage_errors": 0}


def test_null_herdr_substrate_fails_closed_without_core_state_change(monkeypatch):
    monkeypatch.delenv("HERDR_ENV", raising=False)
    provider = HerdrCliSnapshotProvider(runner=lambda *args, **kwargs: None)
    try:
        provider.snapshot()
    except TransportError as exc:
        assert "HERDR_ENV=1" in str(exc)
    else:
        raise AssertionError("null Herdr substrate was not rejected")


def test_store_backup_restore_preserves_pending_observation(tmp_path: Path):
    import sqlite3
    source = tmp_path / "herdr.sqlite"
    backup = tmp_path / "herdr.sqlite.backup"
    event = normalize(notification(), pane(), generation="rollback")
    store = ObservationStore(str(source))
    assert store.receive(event) is True
    store.db.commit()
    with sqlite3.connect(backup) as destination:
        store.db.backup(destination)
    store.db.close()
    restored = tmp_path / "herdr.sqlite.restored"
    with sqlite3.connect(restored) as destination, sqlite3.connect(backup) as saved:
        saved.backup(destination)
    recovered = ObservationStore(str(restored))
    assert recovered.pending()[0]["event_id"] == event["event_id"]


def test_reconnecting_stream_reopens_read_only_subscription_after_poll_failure():
    class FakeStream:
        def __init__(self):
            self.closed = False
        def poll(self):
            raise TransportError("socket closed")
        def close(self):
            self.closed = True
    class FakeTransport:
        def __init__(self):
            self.opened = 0
            self.stream = FakeStream()
        def subscribe_agent_status_stream(self, pane_id):
            self.opened += 1
            return self.stream
    transport = FakeTransport()
    stream = ReconnectingAgentStatusStream(transport, "p1")
    stream.connect()
    try:
        stream.poll()
    except TransportError:
        pass
    else:
        raise AssertionError("poll unexpectedly succeeded")
    assert stream.health.state == "degraded"
    assert stream.reconnect() == 0.25
    assert transport.opened == 2


def test_unix_transport_reconnects_after_socket_replacement(tmp_path: Path):
    import os
    import socket
    import threading

    socket_path = str(tmp_path / "herdr.sock")
    errors = []

    def serve(close_after_ack: bool, ready: threading.Event):
        server = socket.socket(socket.AF_UNIX)
        try:
            server.bind(socket_path)
            server.listen(1)
            ready.set()
            connection, _ = server.accept()
            with connection:
                request = b""
                while b"\n" not in request:
                    request = connection.recv(4096)
                    if not request:
                        return
                connection.sendall(b'{"id":"ack","result":{"type":"subscription_started"}}\n')
                if not close_after_ack:
                    while connection.recv(4096):
                        pass
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
            ready.set()
        finally:
            server.close()

    first_ready = threading.Event()
    first = threading.Thread(target=serve, args=(True, first_ready), daemon=True)
    first.start()
    assert first_ready.wait(2)
    transport = UnixSocketReadOnlyTransport(socket_path, timeout_seconds=1)
    stream = ReconnectingAgentStatusStream(transport, "w:p")
    stream.connect()
    try:
        stream.poll()
    except TransportError:
        pass
    else:
        raise AssertionError("closed replacement source was not detected")
    first.join(2)
    os.unlink(socket_path)

    second_ready = threading.Event()
    second = threading.Thread(target=serve, args=(False, second_ready), daemon=True)
    second.start()
    assert second_ready.wait(2)
    assert stream.reconnect() == 0.25
    assert stream.health.state == "healthy"
    stream.subscription.close()
    second.join(2)
    assert errors == []


def test_correlation_disposition_is_durable_and_idempotent(tmp_path: Path):
    path = str(tmp_path / "herdr.sqlite")
    first = ObservationStore(path)
    assert first.record_disposition("e1", "UNATTRIBUTED", "awaiting registry") is True
    assert first.record_disposition("e1", "PROJECTED", "late retry") is False
    first.db.close()
    second = ObservationStore(path)
    assert second.disposition("e1") == ("UNATTRIBUTED", "awaiting registry")


def test_durable_store_bounds_pending_rows_and_records_eviction():
    store = ObservationStore(max_count=1, max_bytes=10000)
    first = normalize(notification(seq=1), pane(), generation="g1")
    second = normalize(notification(seq=2), pane(), generation="g1")
    assert store.receive(first) is True
    assert store.receive(second) is True
    assert [item["event_id"] for item in store.pending()] == [second["event_id"]]
    assert store.eviction_facts()[0]["event_id"] == first["event_id"]


def test_durable_unattributed_rows_share_count_bounds():
    store = ObservationStore(max_count=1, max_bytes=10000)
    first = normalize(notification(seq=1), pane(), generation="g1")
    second = normalize(notification(seq=2), pane(), generation="g1")
    assert store.record_unattributed(first, "missing") is True
    assert store.record_unattributed(second, "missing") is True
    assert [item["event_id"] for item in store.unattributed()] == [second["event_id"]]
    assert store.eviction_facts()[0]["source"] == "unattributed"


def test_durable_age_bound_evicts_old_inbox_row(tmp_path: Path):
    path = str(tmp_path / "herdr.sqlite")
    store = ObservationStore(path, max_age_seconds=1)
    event = normalize(notification(), pane(), generation="g1")
    assert store.receive(event) is True
    store.db.execute("UPDATE inbox SET received_at=1.0 WHERE event_id=?", (event["event_id"],))
    store.db.commit()
    newer = normalize(notification(seq=2), pane(), generation="g1")
    assert store.receive(newer) is True
    assert event["event_id"] not in [item["event_id"] for item in store.pending()]
    assert any(f["event_id"] == event["event_id"] and f["reason"] == "age" for f in store.eviction_facts())


def test_store_keeps_source_and_execution_high_water_marks_monotonic():
    store = ObservationStore()
    store.checkpoint("herdr", 8)
    store.checkpoint_execution("exec-1", 11)
    store.checkpoint_execution("exec-1", 4)
    assert store.high_water("herdr") == 8
    assert store.execution_high_water("exec-1") == 11


def test_outbox_is_bounded_and_evictions_are_recorded():
    store = ObservationStore(max_count=1, max_bytes=10000)
    first = normalize(notification(seq=1), pane(), generation="outbox")
    second = normalize(notification(seq=2), pane(), generation="outbox")
    store.receive(first)
    assert store.project_once(first["event_id"], {"event_id": first["event_id"]}) is True
    store.receive(second)
    assert store.project_once(second["event_id"], {"event_id": second["event_id"]}) is True
    assert any(f["source"] == "outbox" for f in store.eviction_facts())


def test_byte_pressure_is_bounded_and_audited_for_durable_and_memory_buffers():
    event = normalize(notification(), pane(), generation="bytes")
    store = ObservationStore(max_count=10, max_bytes=10)
    assert store.receive(event) is True
    assert store.pending() == []
    assert any(f["source"] == "inbox" and f["reason"] == "limit" for f in store.eviction_facts())

    buffer = BoundedObservationBuffer(max_count=10, max_bytes=10)
    buffer.append(event)
    assert len(buffer) == 0
    assert buffer.evictions[0].event_id == event["event_id"]
