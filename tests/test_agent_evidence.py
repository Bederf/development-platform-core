import hashlib
import tempfile
import unittest
from pathlib import Path

from adapters.agent_evidence import AgentEvidenceError, AgentLifecycle, ArtifactCollector
from adapters.agent_runtime import AgentExecutionIdentity


class AgentEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identity = AgentExecutionIdentity("cp-1", "work-1", "run-1", "exec-1", "attempt-1")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_lifecycle_maps_execution_without_verification_state(self) -> None:
        lifecycle = AgentLifecycle()
        lifecycle.transition("AUTHORIZED", "readiness_passed")
        lifecycle.transition("STARTING", "dsh_process_spawned")
        lifecycle.transition("RUNNING", "dsh_session_bound", provider_session_id="dsh-1")
        lifecycle.transition("SUCCEEDED", "dsh_exit_zero", provider_session_id="dsh-1")

        self.assertEqual(lifecycle.state, "SUCCEEDED")
        self.assertEqual([event.state for event in lifecycle.events], [
            "REQUESTED", "AUTHORIZED", "STARTING", "RUNNING", "SUCCEEDED",
        ])
        self.assertNotIn("PASS", {event.state for event in lifecycle.events})

    def test_invalid_lifecycle_transition_fails_closed(self) -> None:
        lifecycle = AgentLifecycle()
        with self.assertRaises(AgentEvidenceError):
            lifecycle.transition("RUNNING", "skipped_authorization")

    def test_artifact_is_hashed_and_bound_to_attempt(self) -> None:
        source = self.root / "result.txt"
        source.write_text("provider output\n", encoding="utf-8")
        record = ArtifactCollector(self.root / "artifacts").capture(
            source,
            identity=self.identity,
            provider_session_id="dsh-1",
        )

        self.assertEqual(record.sha256, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(record.size, source.stat().st_size)
        self.assertEqual(Path(record.path).read_text(encoding="utf-8"), "provider output\n")
        self.assertEqual(record.identity.attempt_id, "attempt-1")

    def test_artifact_record_does_not_contain_credentials(self) -> None:
        source = self.root / "result.txt"
        source.write_text("safe result\n", encoding="utf-8")
        record = ArtifactCollector(self.root / "artifacts").capture(
            source,
            identity=self.identity,
            provider_session_id="dsh-1",
        )

        self.assertNotIn("DEEPSEEK_API_KEY", repr(record))
        self.assertNotIn("secret", repr(record))


if __name__ == "__main__":
    unittest.main()
