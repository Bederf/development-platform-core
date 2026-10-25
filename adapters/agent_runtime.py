"""Provider-neutral identity projection for agent runtime adapters.

The platform owns execution identity. A provider session is an observation
attached to one platform attempt; it cannot replace or create platform IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class AgentRuntimeIdentityError(ValueError):
    """Raised when runtime identity cannot be bound without ambiguity."""


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentRuntimeIdentityError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True)
class AgentExecutionIdentity:
    """Platform-owned identity for one execution attempt."""

    control_plane_id: str
    work_item_id: str
    run_id: str
    execution_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        for field in (
            "control_plane_id",
            "work_item_id",
            "run_id",
            "execution_id",
            "attempt_id",
        ):
            _required(getattr(self, field), field)


@dataclass(frozen=True)
class ProviderSessionObservation:
    """Provider-native session identity observed under one platform attempt."""

    provider: str
    session_id: str
    platform: AgentExecutionIdentity

    def __post_init__(self) -> None:
        _required(self.provider, "provider")
        _required(self.session_id, "session_id")


class AgentRuntimeIdentityBridge:
    """Bind provider observations to immutable platform execution identity."""

    schema = "agent-runtime.v1"

    def __init__(self, identity: AgentExecutionIdentity, *, provider: str) -> None:
        _required(provider, "provider")
        self.identity = identity
        self.provider = provider
        self._session: ProviderSessionObservation | None = None

    @property
    def session(self) -> ProviderSessionObservation | None:
        """Return the bound provider session, if the adapter observed one."""

        return self._session

    def bind_session(self, session_id: str) -> ProviderSessionObservation:
        """Bind one provider session and reject replacement by another session."""

        _required(session_id, "session_id")
        if self._session is not None and self._session.session_id != session_id:
            raise AgentRuntimeIdentityError("one platform attempt cannot bind multiple provider sessions")
        self._session = ProviderSessionObservation(self.provider, session_id, self.identity)
        return self._session

    def project_context(self, startup_context: Mapping[str, Any]) -> dict[str, Any]:
        """Project startup authority without allowing provider fields to override it."""

        if not isinstance(startup_context, Mapping):
            raise AgentRuntimeIdentityError("startup_context must be a mapping")
        projected = dict(startup_context)
        projected["agent_runtime"] = {
            "schema": self.schema,
            "provider": self.provider,
            "control_plane_id": self.identity.control_plane_id,
            "work_item_id": self.identity.work_item_id,
            "run_id": self.identity.run_id,
            "execution_id": self.identity.execution_id,
            "attempt_id": self.identity.attempt_id,
        }
        if self._session is not None:
            projected["agent_runtime"]["provider_session_id"] = self._session.session_id
        return projected
