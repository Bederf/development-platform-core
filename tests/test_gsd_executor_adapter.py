from __future__ import annotations

import unittest

from adapters.agent_runtime import AgentExecutionIdentity
from adapters.gsd_execution_admission import AdmissionDecision
from adapters.gsd_execution_identity import OperationIdentity
from adapters.gsd_executor_adapter import ExecutorAdapterError, build_executor_dispatch_request


def _identity() -> AgentExecutionIdentity:
    return AgentExecutionIdentity("dpc", "task-1", "run-1", "execution-1", "attempt-1")


def _admission() -> AdmissionDecision:
    return AdmissionDecision("op-1", "task-1", "attempt-1", "slot-1", "graph-1", 7, "slot:task-1")


def _context() -> dict:
    return {"schema": "agent-startup-context.v1", "current_objective": "qualify adapter"}


class ExecutorAdapterTests(unittest.TestCase):
    def test_maps_admitted_operation_to_existing_runtime_v1(self) -> None:
        operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
        request = build_executor_dispatch_request(
            identity=_identity(), admission=_admission(), operation=operation,
            agent="codex", mode="read_only", startup_context=_context(),
            objective="qualify adapter", request_id="op-1-execute",
        )
        payload = request.to_runtime_request()
        self.assertEqual(payload["schema"], "agent-runtime.v1")
        self.assertEqual(payload["execution"]["attempt_id"], "attempt-1")
        self.assertEqual(payload["task"]["objective"], "qualify adapter")
        self.assertEqual(request.evidence()["input_digest"], operation.input_digest)

    def test_rejects_admission_attempt_mismatch(self) -> None:
        operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
        with self.assertRaises(ExecutorAdapterError):
            build_executor_dispatch_request(
                identity=AgentExecutionIdentity("dpc", "task-1", "run-1", "execution-1", "other-attempt"),
                admission=_admission(), operation=operation, agent="codex", mode="read_only",
                startup_context=_context(), objective="qualify adapter", request_id="op-1-execute",
            )

    def test_rejects_unsupported_profile_and_invalid_context(self) -> None:
        operation = OperationIdentity.from_input("op-1", {"task": "task-1"})
        for agent, context in (("gemini", _context()), ("codex", {"schema": "wrong.v1"})):
            with self.subTest(agent=agent), self.assertRaises(ExecutorAdapterError):
                build_executor_dispatch_request(
                    identity=_identity(), admission=_admission(), operation=operation,
                    agent=agent, mode="read_only", startup_context=context,
                    objective="qualify adapter", request_id="op-1-execute",
                )


if __name__ == "__main__":
    unittest.main()
