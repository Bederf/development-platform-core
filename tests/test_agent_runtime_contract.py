"""Fake-provider conformance for the provider-neutral agent-runtime.v1 envelope."""

import json
import unittest
from datetime import datetime, timezone

from jsonschema import Draft202012Validator, RefResolver, ValidationError

from tests.test_contracts import CONTRACTS


def validate(payload: dict) -> None:
    schema_path = CONTRACTS / "agent-runtime.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    resolver = RefResolver(schema_path.as_uri(), schema)
    Draft202012Validator(schema, resolver=resolver).validate(payload)


def execution(attempt: str = "attempt-1") -> dict:
    return {
        "control_plane_id": "cp-1",
        "work_item_id": "work-1",
        "run_id": "run-1",
        "execution_id": f"execution-{attempt}",
        "attempt_id": attempt,
    }


def startup_context() -> dict:
    return {
        "schema": "agent-startup-context.v1",
        "project_id": "platform-core",
        "repository_root": "/workspace/project",
        "knowledge_root": "knowledge/",
        "planning_root": "00-GSD-Phases/",
        "session": {"session_id": "session-1"},
        "repository_intelligence": {
            "schema": "repository-intelligence.v1",
            "status": "UNAVAILABLE",
            "provider": "fake",
            "generated_at": "2026-08-21T00:00:00Z",
            "indexed_revision": "unknown",
            "trusted": False,
            "relevant_files": [],
            "relevant_symbols": [],
            "notes": [],
            "freshness_evidence": [],
        },
        "agents": {"fake-provider": True},
        "session_brief": {"status": "unavailable", "path": None, "reason": "fake"},
        "runtime_history": {"status": "unavailable", "recent_runs": [], "reason": "fake"},
    }


class FakeAgentRuntime:
    """In-memory provider that returns independent, correlated results."""

    def __init__(self) -> None:
        self.model = {"provider": "fake-provider", "model": "fake-model"}
        self.requests: set[str] = set()

    def handle(self, request: dict) -> dict:
        validate(request)
        self.requests.add(request["request_id"])
        result = {
            "schema": "agent-runtime.v1",
            "message_type": "result",
            "operation": request["operation"],
            "request_id": f"result-for-{request['request_id']}",
            "in_reply_to": request["request_id"],
            "execution": request["execution"],
            "status": "ACCEPTED",
        }
        operation = request["operation"]
        if operation == "select_model":
            self.model = dict(request["model"])
            result["selected_model"] = dict(self.model)
        elif operation == "execute":
            result.update({
                "status": "SUCCEEDED",
                "provider_session": {"provider": "fake-provider", "session_id": "session-1"},
                "selected_model": dict(self.model),
                "events": [{
                    "event_id": "event-1",
                    "event_type": "execution_completed",
                    "sequence": 0,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "payload": {"fact": "fake execution completed"},
                }],
                "artifacts": [{
                    "artifact_id": "artifact-1",
                    "kind": "task-result",
                    "uri": "memory://artifact-1",
                    "digest": None,
                    "producer": "fake-provider",
                    "publication": "PRODUCED",
                }],
            })
        elif operation == "cancel":
            result.update({
                "status": "CANCELLED",
                "cancellation": {"requested": True, "completed": True, "reason": request["reason"]},
            })
        elif operation == "retry":
            result["retry"] = {
                "parent_attempt_id": request["previous_attempt_id"],
                "new_attempt_id": request["execution"]["attempt_id"],
            }
        validate(result)
        return result

    def accept_result(self, request: dict, result: dict) -> None:
        validate(result)
        if result["in_reply_to"] != request["request_id"]:
            raise ValueError("runtime result is correlated to a different request")


class AgentRuntimeContractTests(unittest.TestCase):
    def result_for(self, request: dict, status: str, **fields: object) -> dict:
        result = {
            "schema": "agent-runtime.v1",
            "message_type": "result",
            "operation": request["operation"],
            "request_id": f"result-for-{request['request_id']}",
            "in_reply_to": request["request_id"],
            "execution": request["execution"],
            "status": status,
        }
        result.update(fields)
        validate(result)
        return result

    def test_fake_runtime_covers_successful_lifecycle_and_external_forge_boundary(self) -> None:
        runtime = FakeAgentRuntime()
        start = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "start",
            "request_id": "lifecycle-start",
            "execution": execution(),
            "startup_context": startup_context(),
        }
        execute = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "execute",
            "request_id": "lifecycle-execute",
            "execution": execution(),
            "task": {"objective": "complete the lifecycle"},
        }
        publish = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "collect_artifacts",
            "request_id": "lifecycle-publish",
            "execution": execution(),
        }

        accepted = runtime.handle(start)
        running = self.result_for(execute, "RUNNING", selected_model=runtime.model)
        succeeded = runtime.handle(execute)
        published = self.result_for(
            publish,
            "SUCCEEDED",
            artifacts=[{
                "artifact_id": "artifact-1",
                "kind": "task-result",
                "uri": "memory://artifact-1",
                "digest": None,
                "producer": "fake-provider",
                "publication": "PUBLISHED",
            }],
        )

        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertEqual(running["status"], "RUNNING")
        self.assertEqual(succeeded["status"], "SUCCEEDED")
        self.assertEqual(published["artifacts"][0]["publication"], "PUBLISHED")
        self.assertNotIn("forge_result", published)

    def test_fake_runtime_covers_failure_lifecycle(self) -> None:
        request = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "execute",
            "request_id": "lifecycle-failure",
            "execution": execution(),
            "task": {"objective": "fail deterministically"},
        }
        failed = self.result_for(
            request,
            "FAILED",
            selected_model={"provider": "fake-provider", "model": "fake-model"},
            error={"code": "FAKE_FAILURE", "message": "intentional fake failure", "retryable": True},
        )
        self.assertEqual(failed["status"], "FAILED")
        self.assertTrue(failed["error"]["retryable"])

    def test_fake_runtime_covers_requested_then_completed_cancellation(self) -> None:
        request = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "cancel",
            "request_id": "lifecycle-cancel",
            "execution": execution(),
            "reason": "operator requested cancellation",
        }
        requested = self.result_for(
            request,
            "CANCEL_REQUESTED",
            cancellation={"requested": True, "completed": False, "reason": request["reason"]},
        )
        completed = self.result_for(
            request,
            "CANCELLED",
            cancellation={"requested": True, "completed": True, "reason": request["reason"]},
        )
        self.assertFalse(requested["cancellation"]["completed"])
        self.assertTrue(completed["cancellation"]["completed"])

    def test_fake_runtime_covers_retry_as_a_new_attempt(self) -> None:
        request = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "retry",
            "request_id": "lifecycle-retry",
            "execution": execution("attempt-2"),
            "previous_attempt_id": "attempt-1",
        }
        retried = FakeAgentRuntime().handle(request)
        self.assertEqual(retried["status"], "ACCEPTED")
        self.assertEqual(retried["retry"]["parent_attempt_id"], "attempt-1")
        self.assertEqual(retried["retry"]["new_attempt_id"], "attempt-2")

    def test_fake_runtime_returns_correlated_result_with_session_events_and_artifact(self) -> None:
        runtime = FakeAgentRuntime()
        request = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "execute",
            "request_id": "request-execute",
            "execution": execution(),
            "task": {"objective": "produce a bounded fake result"},
        }

        result = runtime.handle(request)

        self.assertEqual(result["in_reply_to"], request["request_id"])
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["provider_session"]["session_id"], "session-1")
        self.assertEqual(result["events"][0]["event_type"], "execution_completed")
        self.assertEqual(result["artifacts"][0]["publication"], "PRODUCED")
        runtime.accept_result(request, result)

    def test_model_selection_is_applied_to_later_execution(self) -> None:
        runtime = FakeAgentRuntime()
        selection = runtime.handle({
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "select_model",
            "request_id": "request-model",
            "execution": execution(),
            "model": {"provider": "another-provider", "model": "another-model"},
        })
        self.assertEqual(selection["selected_model"]["provider"], "another-provider")

        result = runtime.handle({
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "execute",
            "request_id": "request-execute-after-selection",
            "execution": execution(),
            "task": {"objective": "use the selected model"},
        })
        self.assertEqual(result["selected_model"]["model"], "another-model")

    def test_cancellation_distinguishes_requested_and_completed(self) -> None:
        result = FakeAgentRuntime().handle({
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "cancel",
            "request_id": "request-cancel",
            "execution": execution(),
            "reason": "operator requested cancellation",
        })
        self.assertEqual(result["status"], "CANCELLED")
        self.assertTrue(result["cancellation"]["requested"])
        self.assertTrue(result["cancellation"]["completed"])

    def test_retry_result_links_parent_and_new_attempt(self) -> None:
        result = FakeAgentRuntime().handle({
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "retry",
            "request_id": "request-retry",
            "execution": execution("attempt-2"),
            "previous_attempt_id": "attempt-1",
        })
        self.assertEqual(result["retry"], {"parent_attempt_id": "attempt-1", "new_attempt_id": "attempt-2"})

    def test_result_without_correlation_is_invalid(self) -> None:
        result = FakeAgentRuntime().handle({
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "execute",
            "request_id": "request-invalid-result",
            "execution": execution(),
            "task": {"objective": "test correlation"},
        })
        result.pop("in_reply_to")
        with self.assertRaises(ValidationError):
            validate(result)

    def test_result_correlated_to_another_request_is_rejected(self) -> None:
        runtime = FakeAgentRuntime()
        request = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "execute",
            "request_id": "request-original",
            "execution": execution(),
            "task": {"objective": "test correlation"},
        }
        result = runtime.handle(request)
        result["in_reply_to"] = "request-other"
        with self.assertRaises(ValueError):
            runtime.accept_result(request, result)

    def test_runtime_result_does_not_claim_forge_verification(self) -> None:
        result = FakeAgentRuntime().handle({
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "execute",
            "request_id": "request-authority",
            "execution": execution(),
            "task": {"objective": "produce evidence"},
        })
        self.assertNotIn("verification_status", result)
        self.assertNotIn("forge_result", result)


if __name__ == "__main__":
    unittest.main()
