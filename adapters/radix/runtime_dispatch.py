"""Provider-neutral Radix dispatch to ``agent-runtime.v1`` providers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from ..agent_runtime import AgentExecutionIdentity
from .startup import StartupResolution


class RuntimeDispatchError(ValueError):
    """Raised when a runtime cannot be selected or invoked safely."""


class AgentRuntimeProvider(Protocol):
    def handle(self, request: Mapping[str, Any], *, cwd: str | Path, result_sink: Any = None) -> dict[str, Any]:
        """Handle one agent-runtime.v1 request."""


@dataclass(frozen=True)
class RuntimeSelection:
    """Provider-neutral runtime selection supplied by platform policy."""

    name: str
    model: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise RuntimeDispatchError("runtime selection name is required")
        if self.model is not None:
            if set(self.model) != {"provider", "model"}:
                raise RuntimeDispatchError("runtime model must contain provider and model")
            if any(not isinstance(value, str) or not value.strip() for value in self.model.values()):
                raise RuntimeDispatchError("runtime model values must be non-empty strings")


@dataclass(frozen=True)
class RuntimeInvocation:
    """The correlated results of one Radix start/execute dispatch."""

    runtime_name: str
    start: dict[str, Any]
    execute: dict[str, Any]


class RadixRuntimeDispatcher:
    """Resolve startup authority and invoke a configured runtime provider."""

    def __init__(self, providers: Mapping[str, AgentRuntimeProvider]) -> None:
        self._providers = dict(providers)

    def invoke(
        self,
        resolution: StartupResolution,
        *,
        selection: RuntimeSelection,
        identity: AgentExecutionIdentity,
        cwd: str | Path,
        request_prefix: str,
        result_sink: Any = None,
    ) -> RuntimeInvocation:
        if not resolution.ready or not resolution.execution_allowed or resolution.context is None:
            raise RuntimeDispatchError("startup resolution is not executable")
        provider = self._providers.get(selection.name)
        if provider is None:
            raise RuntimeDispatchError(f"runtime is not configured: {selection.name}")

        start_request = self._request(
            operation="start",
            request_id=f"{request_prefix}-start",
            identity=identity,
            startup_context=resolution.context,
        )
        start_result = provider.handle(start_request, cwd=cwd)
        if start_result.get("status") != "ACCEPTED":
            raise RuntimeDispatchError("runtime rejected startup")

        execute_fields: dict[str, Any] = {"task": {"objective": resolution.context["current_objective"]}}
        if selection.model is not None:
            execute_fields["model"] = dict(selection.model)
        execute_request = self._request(
            operation="execute",
            request_id=f"{request_prefix}-execute",
            identity=identity,
            **execute_fields,
        )
        execute_result = provider.handle(execute_request, cwd=cwd, result_sink=result_sink)
        if execute_result.get("in_reply_to") != execute_request["request_id"]:
            raise RuntimeDispatchError("runtime result correlation failed")
        if execute_result.get("execution") != identity.__dict__:
            raise RuntimeDispatchError("runtime changed platform execution identity")
        return RuntimeInvocation(selection.name, start_result, execute_result)

    def collect_artifacts(
        self,
        invocation: RuntimeInvocation,
        *,
        identity: AgentExecutionIdentity,
        cwd: str | Path,
        request_id: str,
    ) -> dict[str, Any]:
        """Publish runtime-produced artifacts through the generic contract."""

        provider = self._providers.get(invocation.runtime_name)
        if provider is None:
            raise RuntimeDispatchError(f"runtime is not configured: {invocation.runtime_name}")
        request = self._request(
            operation="collect_artifacts",
            request_id=request_id,
            identity=identity,
        )
        result = provider.handle(request, cwd=cwd)
        if result.get("in_reply_to") != request_id:
            raise RuntimeDispatchError("artifact result correlation failed")
        if result.get("execution") != identity.__dict__:
            raise RuntimeDispatchError("artifact result changed platform execution identity")
        return result

    @staticmethod
    def _request(*, operation: str, request_id: str, identity: AgentExecutionIdentity, **fields: Any) -> dict[str, Any]:
        request = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": operation,
            "request_id": request_id,
            "execution": identity.__dict__,
        }
        request.update(fields)
        return request
