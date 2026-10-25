import unittest

from adapters.control_plane import (
    ControlPlaneProjection,
    FakeControlPlaneProvider,
    InvalidControlPlaneEvent,
)


class ControlPlaneAdapterConformanceTests(unittest.TestCase):
    def test_fake_provider_preserves_identity_and_deduplicates_events(self) -> None:
        provider = FakeControlPlaneProvider()
        adapter = ControlPlaneProjection()
        event = provider.event("attempt_started")

        self.assertEqual(adapter.ingest(event), "accepted")
        self.assertEqual(adapter.ingest(event), "duplicate")
        stored = adapter.events[event["event_id"]]
        self.assertEqual(stored.work_item_id, "work-001")
        self.assertEqual(stored.execution_id, "execution-001")
        self.assertEqual(stored.attempt_id, "attempt-001")
        self.assertEqual(len(adapter.events), 1)

    def test_retry_lineage_keeps_attempts_under_one_work_item(self) -> None:
        provider = FakeControlPlaneProvider()
        adapter = ControlPlaneProjection()
        first = provider.event("attempt_started")
        adapter.ingest(first)
        second = provider.event("attempt_started")
        second.update({"execution_id": "execution-002", "attempt_id": "attempt-002"})
        adapter.ingest(second)

        self.assertEqual(set(adapter.executions), {"execution-001", "execution-002"})
        self.assertEqual(adapter.executions["execution-001"].work_item_id, "work-001")
        self.assertEqual(adapter.executions["execution-001"].attempts, {"attempt-001": ["event-1"]})
        self.assertEqual(adapter.executions["execution-002"].attempts, {"attempt-002": ["event-2"]})

    def test_control_plane_done_cannot_authorize_completion(self) -> None:
        provider = FakeControlPlaneProvider()
        adapter = ControlPlaneProjection()
        adapter.ingest(provider.event("control_plane_done"))

        self.assertFalse(adapter.executions["execution-001"].completion_authorized)

    def test_artifact_and_forge_pass_authorize_completion(self) -> None:
        provider = FakeControlPlaneProvider()
        adapter = ControlPlaneProjection()
        adapter.ingest(provider.event("artifact_produced", artifact_id="artifact-001"))
        adapter.ingest(provider.event("forge_verification", status="PASSED"))

        projection = adapter.executions["execution-001"]
        self.assertEqual(projection.artifacts, {"artifact-001"})
        self.assertEqual(projection.forge_status, "PASSED")
        self.assertTrue(projection.completion_authorized)

    def test_forge_failure_blocks_completion_even_after_artifact(self) -> None:
        provider = FakeControlPlaneProvider()
        adapter = ControlPlaneProjection()
        adapter.ingest(provider.event("artifact_produced", artifact_id="artifact-001"))
        adapter.ingest(provider.event("forge_verification", status="FAILED"))

        projection = adapter.executions["execution-001"]
        self.assertFalse(projection.completion_authorized)
        self.assertEqual(projection.failure_reasons, ["forge_failed"])

    def test_malformed_event_fails_closed(self) -> None:
        with self.assertRaises(InvalidControlPlaneEvent):
            ControlPlaneProjection().ingest({"event_id": "event-1"})

    def test_runtime_failure_reason_is_not_collapsed(self) -> None:
        provider = FakeControlPlaneProvider()
        adapter = ControlPlaneProjection()
        adapter.ingest(provider.event("execution_failed", reason="toolchain_missing"))
        adapter.ingest(provider.event("execution_failed", reason="agent_not_authenticated"))

        self.assertEqual(
            adapter.executions["execution-001"].failure_reasons,
            ["toolchain_missing", "agent_not_authenticated"],
        )


if __name__ == "__main__":
    unittest.main()
