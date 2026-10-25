"""Lifecycle and artifact evidence for provider runtime adapters."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .agent_runtime import AgentExecutionIdentity


LifecycleState = Literal["REQUESTED", "AUTHORIZED", "STARTING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]


class AgentEvidenceError(ValueError):
    """Raised when lifecycle or artifact evidence is invalid."""


@dataclass(frozen=True)
class LifecycleEvent:
    """One ordered provider lifecycle observation."""

    sequence: int
    state: LifecycleState
    reason: str
    provider_session_id: str | None = None


class AgentLifecycle:
    """Enforce the platform lifecycle without treating provider success as verification."""

    _allowed: dict[LifecycleState, set[LifecycleState]] = {
        "REQUESTED": {"AUTHORIZED", "FAILED", "CANCELLED"},
        "AUTHORIZED": {"STARTING", "FAILED", "CANCELLED"},
        "STARTING": {"RUNNING", "FAILED", "CANCELLED"},
        "RUNNING": {"SUCCEEDED", "FAILED", "CANCELLED"},
        "SUCCEEDED": set(),
        "FAILED": set(),
        "CANCELLED": set(),
    }

    def __init__(self) -> None:
        self.state: LifecycleState = "REQUESTED"
        self.events: list[LifecycleEvent] = [LifecycleEvent(0, "REQUESTED", "execution_requested")]

    def transition(self, state: LifecycleState, reason: str, *, provider_session_id: str | None = None) -> LifecycleEvent:
        if state not in self._allowed[self.state]:
            raise AgentEvidenceError(f"invalid lifecycle transition {self.state} -> {state}")
        if not reason:
            raise AgentEvidenceError("lifecycle transition reason is required")
        self.state = state
        event = LifecycleEvent(len(self.events), state, reason, provider_session_id)
        self.events.append(event)
        return event


@dataclass(frozen=True)
class ArtifactRecord:
    """Immutable artifact evidence; it contains no credential or model output."""

    artifact_id: str
    identity: AgentExecutionIdentity
    provider_session_id: str
    path: str
    size: int
    sha256: str


class ArtifactCollector:
    """Copy provider output into an attempt-owned artifact store and hash it."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def capture(
        self,
        source: str | Path,
        *,
        identity: AgentExecutionIdentity,
        provider_session_id: str,
    ) -> ArtifactRecord:
        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise AgentEvidenceError("artifact source is not a file")
        if not provider_session_id:
            raise AgentEvidenceError("provider_session_id is required")

        attempt_root = self.root / identity.attempt_id
        attempt_root.mkdir(parents=True, exist_ok=True)
        destination = attempt_root / source_path.name
        with tempfile.NamedTemporaryFile(prefix=".artifact-", dir=attempt_root, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(source_path, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        return ArtifactRecord(
            artifact_id=f"artifact-{identity.execution_id}-{identity.attempt_id}-{source_path.name}",
            identity=identity,
            provider_session_id=provider_session_id,
            path=str(destination),
            size=destination.stat().st_size,
            sha256=digest,
        )
