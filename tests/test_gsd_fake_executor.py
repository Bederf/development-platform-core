from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver

from adapters.agent_runtime import AgentExecutionIdentity
from adapters.gsd_execution_admission import AdmissionDecision
from adapters.gsd_execution_identity import OperationIdentity
from adapters.gsd_executor_adapter import build_executor_dispatch_request
from adapters.gsd_fake_executor import FakeExecutor, FakeExecutorError


ROOT = Path(__file__).parents[1]


def request(operation: OperationIdentity, *, attempt_id: str = "attempt-1"):
    return build_executor_dispatch_request(
        identity=AgentExecutionIdentity("dpc", "task-1", "run-1", "execution-1", attempt_id),
        operation=operation,
        admission=AdmissionDecision("op-1", "task-1", attempt_id, "slot-1", "graph-1", 7, "slot:task-1"),
        agent="codex",
        mode="read_only",
        startup_context={"schema": "agent-startup-context.v1", "current_objective": "qualify adapter"},
        objective="qualify adapter",
        request_id=f"{operation.operation_id}-execute",
    )


class FakeExecutorTests(unittest.TestCase):
    def test_executes_once_and_returns_contract_result(self) -> None:
        executor = FakeExecutor()
        operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
        result = executor.execute(request(operation))
        self.assertEqual(result.response["status"], "SUCCEEDED")
        self.assertEqual(result.response["execution"]["attempt_id"], "attempt-1")
        self.assertEqual(result.evidence["input_digest"], operation.input_digest)
        self.assertEqual(executor.invocation_count, 1)

    def test_duplicate_dispatch_is_idempotent(self) -> None:
        executor = FakeExecutor()
        operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
        first = executor.execute(request(operation))
        second = executor.execute(request(operation))
        self.assertEqual(first, second)
        self.assertEqual(executor.invocation_count, 1)

    def test_conflicting_input_and_attempt_fail_closed(self) -> None:
        executor = FakeExecutor()
        executor.execute(request(OperationIdentity.from_input("op-1", {"task": "task-1"})))
        with self.assertRaises(FakeExecutorError):
            executor.execute(request(OperationIdentity.from_input("op-1", {"task": "other"})))
        with self.assertRaises(FakeExecutorError):
            executor.execute(request(OperationIdentity.from_input("op-1", {"task": "task-1"}), attempt_id="attempt-2"))
        self.assertEqual(executor.invocation_count, 1)

    def test_result_is_valid_existing_runtime_contract(self) -> None:
        executor = FakeExecutor()
        operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
        result = executor.execute(request(operation)).response
        schema_path = ROOT / "contracts/agent-runtime.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema, resolver=RefResolver(schema_path.as_uri(), schema)).validate(result)


if __name__ == "__main__":
    unittest.main()
