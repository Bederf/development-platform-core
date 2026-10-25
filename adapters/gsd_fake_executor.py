"""Deterministic in-memory fake executor for P047-T002 conformance tests.

The fake executor models adapter acknowledgement only. It never launches a
process, invokes a provider or touches a workspace.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .gsd_executor_adapter import ExecutorDispatchRequest


class FakeExecutorError(ValueError):
    """Raised when fake dispatch identity is missing or contradictory."""


@dataclass(frozen=True)
class FakeExecutionResult:
    response: dict[str, Any]
    evidence: dict[str, Any]


class FakeExecutor:
    """Return one deterministic result for each exact operation identity."""

    def __init__(self) -> None:
        self._results: dict[str, FakeExecutionResult] = {}
        self.invocation_count = 0

    def execute(self, request: ExecutorDispatchRequest) -> FakeExecutionResult:
        evidence = request.evidence()
        operation_id = evidence["operation_id"]
        existing = self._results.get(operation_id)
        if existing is not None:
            if existing.evidence["input_digest"] != evidence["input_digest"]:
                raise FakeExecutorError("conflicting duplicate operation input")
            if existing.evidence["attempt_id"] != evidence["attempt_id"]:
                raise FakeExecutorError("conflicting duplicate operation attempt")
            return FakeExecutionResult(deepcopy(existing.response), deepcopy(existing.evidence))

        self.invocation_count += 1
        runtime_request = request.to_runtime_request()
        response = {
            "schema": "agent-runtime.v1",
            "message_type": "result",
            "operation": "execute",
            "request_id": f"result:{request.request_id}",
            "in_reply_to": request.request_id,
            "execution": dict(runtime_request["execution"]),
            "status": "SUCCEEDED",
            "selected_model": {"provider": "fake", "model": "conformance"},
        }
        result = FakeExecutionResult(response, evidence)
        self._results[operation_id] = result
        return FakeExecutionResult(deepcopy(response), deepcopy(evidence))
