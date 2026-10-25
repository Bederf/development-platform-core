import tempfile
import unittest
from pathlib import Path

from adapters.agent_runtime import AgentExecutionIdentity
from adapters.radix import RadixRuntimeDispatcher, RuntimeDispatchError, RuntimeSelection, StartupResolution


class FakeRuntime:
    def __init__(self) -> None:
        self.requests = []

    def handle(self, request, *, cwd, result_sink=None):
        self.requests.append((request, Path(cwd)))
        result = {
            "schema": "agent-runtime.v1",
            "message_type": "result",
            "operation": request["operation"],
            "request_id": f"result-{request['request_id']}",
            "in_reply_to": request["request_id"],
            "execution": dict(request["execution"]),
            "status": "ACCEPTED" if request["operation"] == "start" else "SUCCEEDED",
        }
        if request["operation"] == "execute" and "model" in request:
            result["selected_model"] = request["model"]
        if request["operation"] == "collect_artifacts":
            result["artifacts"] = [{
                "artifact_id": "artifact-1",
                "kind": "text/plain",
                "uri": "memory://artifact-1",
                "digest": "sha256:test",
                "producer": "fake-runtime",
                "publication": "PUBLISHED",
            }]
        return result


def resolution(root: Path) -> StartupResolution:
    context = {
        "schema": "agent-startup-context.v1",
        "project_id": "disposable-radix-consumer",
        "repository_root": str(root),
        "knowledge_root": str(root),
        "planning_root": str(root),
        "current_objective": "Run a harmless disposable runtime task",
        "active_phase": None,
        "session": {"session_id": "radix-session-1"},
        "repository_intelligence": {},
        "agents": {"runtime": True},
        "session_brief": {"status": "unavailable"},
        "runtime_history": {"status": "unavailable"},
    }
    return StartupResolution(context, True, True, (), {"source": "test"})


class RadixRuntimeDispatchTests(unittest.TestCase):
    def identity(self) -> AgentExecutionIdentity:
        return AgentExecutionIdentity("cp-1", "work-1", "run-1", "execution-1", "attempt-1")

    def test_radix_dispatches_provider_neutral_start_and_execute_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime()
            invocation = RadixRuntimeDispatcher({"approved-runtime": runtime}).invoke(
                resolution(Path(directory)),
                selection=RuntimeSelection("approved-runtime", {"provider": "model-provider", "model": "model-1"}),
                identity=self.identity(),
                cwd=directory,
                request_prefix="radix-request",
            )

        self.assertEqual(invocation.runtime_name, "approved-runtime")
        self.assertEqual([request["operation"] for request, _ in runtime.requests], ["start", "execute"])
        self.assertEqual(runtime.requests[0][0]["startup_context"]["project_id"], "disposable-radix-consumer")
        self.assertEqual(runtime.requests[1][0]["model"], {"provider": "model-provider", "model": "model-1"})
        self.assertEqual(invocation.execute["execution"], self.identity().__dict__)
        self.assertNotIn("API_KEY", repr(runtime.requests))

    def test_radix_publishes_runtime_artifacts_without_forge_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime()
            dispatcher = RadixRuntimeDispatcher({"approved-runtime": runtime})
            invocation = dispatcher.invoke(
                resolution(Path(directory)),
                selection=RuntimeSelection("approved-runtime"),
                identity=self.identity(),
                cwd=directory,
                request_prefix="radix-request",
            )
            published = dispatcher.collect_artifacts(
                invocation,
                identity=self.identity(),
                cwd=directory,
                request_id="radix-artifacts",
            )

        self.assertEqual(published["status"], "SUCCEEDED")
        self.assertEqual(published["artifacts"][0]["publication"], "PUBLISHED")
        self.assertNotIn("verification", repr(published))

    def test_unknown_runtime_fails_closed_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeDispatchError):
                RadixRuntimeDispatcher({}).invoke(
                    resolution(Path(directory)),
                    selection=RuntimeSelection("missing-runtime"),
                    identity=self.identity(),
                    cwd=directory,
                    request_prefix="radix-request",
                )

    def test_unready_startup_cannot_dispatch(self) -> None:
        blocked = StartupResolution(None, False, False, ("task",), {})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeDispatchError):
                RadixRuntimeDispatcher({"approved-runtime": FakeRuntime()}).invoke(
                    blocked,
                    selection=RuntimeSelection("approved-runtime"),
                    identity=self.identity(),
                    cwd=directory,
                    request_prefix="radix-request",
                )


if __name__ == "__main__":
    unittest.main()
