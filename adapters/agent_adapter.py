"""Provider-neutral construction of ``agent-adapter.v1`` requests.

The adapter owns request normalization only. Provider CLIs, executable policy,
and process dispatch remain separate launcher responsibilities.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


class AgentAdapterError(ValueError):
    """Raised when an agent-adapter request cannot be normalized safely."""


@dataclass(frozen=True)
class AgentAdapterRequest:
    """Immutable in-memory representation of ``agent-adapter.v1``."""

    agent: str
    request_id: str
    startup_context: Mapping[str, Any]
    mode: str
    task_manifest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return an isolated contract payload that callers may mutate."""

        return {
            "schema": "agent-adapter.v1",
            "agent": self.agent,
            "request_id": self.request_id,
            "startup_context": deepcopy(dict(self.startup_context)),
            "mode": self.mode,
            "task_manifest": self.task_manifest,
        }


class AgentAdapter:
    """Normalize a Core startup context into a provider-neutral agent request."""

    _AGENTS = frozenset({"claude", "codex", "opencode"})
    _MODES = frozenset({"interactive", "non_interactive", "read_only"})

    def build(
        self,
        *,
        agent: str,
        request_id: str,
        startup_context: Mapping[str, Any],
        mode: str,
        task_manifest: str | None = None,
    ) -> AgentAdapterRequest:
        if agent not in self._AGENTS:
            raise AgentAdapterError(f"unsupported agent: {agent!r}")
        if not isinstance(request_id, str) or not request_id.strip():
            raise AgentAdapterError("request_id must be a non-empty string")
        if mode not in self._MODES:
            raise AgentAdapterError(f"unsupported mode: {mode!r}")
        if not isinstance(startup_context, Mapping):
            raise AgentAdapterError("startup_context must be a mapping")
        if startup_context.get("schema") != "agent-startup-context.v1":
            raise AgentAdapterError("startup_context must use agent-startup-context.v1")
        if task_manifest is not None and (not isinstance(task_manifest, str) or not task_manifest.strip()):
            raise AgentAdapterError("task_manifest must be null or a non-empty string")
        return AgentAdapterRequest(
            agent=agent,
            request_id=request_id,
            startup_context=deepcopy(dict(startup_context)),
            mode=mode,
            task_manifest=task_manifest,
        )
