import tempfile
import unittest
from pathlib import Path

from adapters.agent_runtime import AgentExecutionIdentity
from adapters.radix import RadixRuntimeDispatcher, RuntimeSelection, StartupResolution
from adapters.verification_lifecycle import ForgeResult, VerificationLifecycle


class FakeRuntime:
    def handle(self, request, *, cwd, result_sink=None):
        result = {
            "schema": "agent-runtime.v1",
            "message_type": "result",
            "operation": request["operation"],
            "request_id": f"result-{request['request_id']}",
            "in_reply_to": request["request_id"],
            "execution": dict(request["execution"]),
            "status": "ACCEPTED" if request["operation"] == "start" else "SUCCEEDED",
        }
        if request["operation"] == "execute":
            result["selected_model"] = {"provider": "fake", "model": "deterministic"}
        if request["operation"] == "collect_artifacts":
            result["artifacts"] = [{
                "artifact_id": "artifact-radix-1",
                "kind": "text/plain",
                "uri": "memory://artifact-radix-1",
                "digest": "sha256:deterministic",
                "producer": "fake-runtime",
                "publication": "PUBLISHED",
            }]
        return result


def startup(root: Path) -> StartupResolution:
    context = {
        "schema": "agent-startup-context.v1",
        "project_id": "disposable-radix-forge-consumer",
        "repository_root": str(root),
        "knowledge_root": str(root),
        "planning_root": str(root),
        "current_objective": "Produce a deterministic artifact",
        "active_phase": None,
        "session": {"session_id": "radix-forge-session"},
        "repository_intelligence": {},
        "agents": {"runtime": True},
        "session_brief": {"status": "unavailable"},
        "runtime_history": {"status": "unavailable"},
    }
    return StartupResolution(context, True, True, (), {})


class RadixRuntimeForgeIntegrationTests(unittest.TestCase):
    def test_runtime_success_requires_independent_forge_pass_for_done(self) -> None:
        identity = AgentExecutionIdentity("cp-1", "work-1", "run-1", "execution-1", "attempt-1")
        with tempfile.TemporaryDirectory() as directory:
            dispatcher = RadixRuntimeDispatcher({"approved-runtime": FakeRuntime()})
            invocation = dispatcher.invoke(
                startup(Path(directory)),
                selection=RuntimeSelection("approved-runtime"),
                identity=identity,
                cwd=directory,
                request_prefix="radix-forge",
            )
            self.assertEqual(invocation.execute["status"], "SUCCEEDED")
            published = dispatcher.collect_artifacts(
                invocation,
                identity=identity,
                cwd=directory,
                request_id="radix-forge-artifacts",
            )
            self.assertEqual(published["artifacts"][0]["publication"], "PUBLISHED")

            lifecycle = VerificationLifecycle(Path(directory) / "verification")
            attempt = lifecycle.create_attempt(
                verification_attempt_id="vat-radix-1",
                gsd_session_id=identity.run_id,
                forge_session_id="forge-radix-1",
                execution_id=identity.execution_id,
                attempt_id=identity.attempt_id,
                repository="disposable-radix-forge-consumer",
                baseline="sha256:deterministic",
            )
            lifecycle.transition(attempt.identity.verification_attempt_id, "VERIFICATION_PENDING", "artifact_published")
            running = lifecycle.transition(attempt.identity.verification_attempt_id, "FORGE_RUNNING", "forge_started")
            self.assertEqual(running.state, "FORGE_RUNNING")
            self.assertNotEqual(invocation.execute["status"], "DONE")

            completed, accepted = lifecycle.apply_result(ForgeResult(
                verification_attempt_id=attempt.identity.verification_attempt_id,
                gsd_session_id=identity.run_id,
                forge_session_id="forge-radix-1",
                execution_id=identity.execution_id,
                attempt_id=identity.attempt_id,
                repository="disposable-radix-forge-consumer",
                baseline="sha256:deterministic",
                lineage=(),
                status="PASS",
                evidence={"artifact_id": "artifact-radix-1"},
            ))

        self.assertTrue(accepted)
        self.assertEqual(completed.state, "DONE")


if __name__ == "__main__":
    unittest.main()
