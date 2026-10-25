"""Controller-owned mapping to the existing provider-neutral runtime contract.

This module implements only P047-T001's adapter boundary. It does not invoke a
provider, harness or executor and does not create or mutate a workspace.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .agent_adapter import AgentAdapter, AgentAdapterError
from .agent_runtime import AgentExecutionIdentity
from .gsd_execution_admission import AdmissionDecision
from .gsd_execution_identity import OperationIdentity, OperationIdentityError


class ExecutorAdapterError(ValueError):
    """Raised when controller-authorized dispatch cannot be mapped safely."""


@dataclass(frozen=True)
class ExecutorDispatchRequest:
    """Immutable controller-bound request before any runtime invocation."""

    identity: AgentExecutionIdentity
    operation: OperationIdentity
    admission: AdmissionDecision
    agent: str
    mode: str
    startup_context: Mapping[str, Any]
    objective: str
    request_id: str

    def __post_init__(self) -> None:
        if self.admission.operation_id != self.operation.operation_id:
            raise ExecutorAdapterError("admission and operation identities differ")
        if self.admission.attempt_id != self.identity.attempt_id:
            raise ExecutorAdapterError("admission and execution attempt identities differ")
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ExecutorAdapterError("dispatch objective must be non-empty")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ExecutorAdapterError("dispatch request_id must be non-empty")

    def to_runtime_request(self) -> dict[str, Any]:
        """Project only fields permitted by the existing agent-runtime.v1 contract."""

        return {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": "execute",
            "request_id": self.request_id,
            "execution": self.identity.__dict__.copy(),
            "startup_context": deepcopy(dict(self.startup_context)),
            "task": {"objective": self.objective},
        }

    def evidence(self) -> dict[str, Any]:
        """Return controller-side identity evidence separate from v1 runtime fields."""

        return {
            "operation_id": self.operation.operation_id,
            "input_digest": self.operation.input_digest,
            "attempt_id": self.identity.attempt_id,
            "task_id": self.admission.task_id,
            "workspace_slot_id": self.admission.workspace_slot_id,
            "graph_revision": self.admission.graph_revision,
        }


def build_executor_dispatch_request(
    *,
    identity: AgentExecutionIdentity,
    operation: OperationIdentity,
    admission: AdmissionDecision,
    agent: str,
    mode: str,
    startup_context: Mapping[str, Any],
    objective: str,
    request_id: str,
) -> ExecutorDispatchRequest:
    """Bind an admitted controller operation to the runtime adapter boundary."""

    try:
        AgentAdapter().build(
            agent=agent,
            request_id=request_id,
            startup_context=startup_context,
            mode=mode,
        )
        OperationIdentity(operation.operation_id, operation.input_digest)
    except (AgentAdapterError, OperationIdentityError, TypeError) as exc:
        raise ExecutorAdapterError(str(exc)) from exc
    if admission.task_id == "":
        raise ExecutorAdapterError("admission task identity is required")
    return ExecutorDispatchRequest(
        identity=identity,
        operation=operation,
        admission=admission,
        agent=agent,
        mode=mode,
        startup_context=deepcopy(dict(startup_context)),
        objective=objective,
        request_id=request_id,
    )
