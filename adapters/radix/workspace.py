"""Resolve Radix invocation directories to authoritative project bindings.

The process working directory is discovery input, never project authority.  A
binding is established only from the nearest valid ``development-platform.yaml``
and is used to reject startup context produced for another repository.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .startup import (
    RadixStartupAdapter,
    RepositoryIntelligence,
    RuntimeHistory,
    SessionBrief,
    StartupConfigurationError,
    StartupResolution,
)


DECLARATION_NAME = "development-platform.yaml"


class WorkspaceDiscoveryError(ValueError):
    """Raised when an invocation directory cannot resolve authoritative project identity."""


class ProjectContextMismatchError(WorkspaceDiscoveryError):
    """Raised when project-bound data belongs to another workspace."""


@dataclass(frozen=True)
class WorkspaceBinding:
    project_id: str
    repository_root: Path
    declaration_path: Path
    invocation_directory: Path
    workspace_id: str
    declaration_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "repository_root": str(self.repository_root),
            "declaration_path": str(self.declaration_path),
            "invocation_directory": str(self.invocation_directory),
            "workspace_id": self.workspace_id,
            "declaration_digest": self.declaration_digest,
        }

    def require_context(self, context: Mapping[str, Any]) -> None:
        """Fail closed unless a startup/session context belongs to this binding."""

        context_project = context.get("project_id")
        if context_project != self.project_id:
            raise ProjectContextMismatchError(
                f"context project_id {context_project!r} does not match resolved project "
                f"{self.project_id!r}"
            )

        context_root = context.get("repository_root")
        if not isinstance(context_root, str) or not context_root.strip():
            raise ProjectContextMismatchError("context repository_root is missing")
        try:
            resolved_context_root = Path(context_root).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ProjectContextMismatchError(
                f"context repository_root cannot be resolved: {context_root!r}"
            ) from exc
        if resolved_context_root != self.repository_root:
            raise ProjectContextMismatchError(
                f"context repository_root {str(resolved_context_root)!r} does not match "
                f"resolved workspace {str(self.repository_root)!r}"
            )

        context_workspace = context.get("workspace_id")
        if context_workspace is not None and context_workspace != self.workspace_id:
            raise ProjectContextMismatchError(
                f"context workspace_id {context_workspace!r} does not match resolved binding"
            )


class WorkspaceResolver:
    """Discover the nearest authoritative project declaration from an invocation path."""

    def __init__(self, declaration_name: str = DECLARATION_NAME) -> None:
        if not declaration_name or Path(declaration_name).name != declaration_name:
            raise ValueError("declaration_name must be one filename")
        self.declaration_name = declaration_name

    def discover(
        self,
        invocation_directory: str | Path,
        *,
        expected_project_id: str | None = None,
    ) -> WorkspaceBinding:
        try:
            invocation = Path(invocation_directory).expanduser().resolve(strict=True)
        except OSError as exc:
            raise WorkspaceDiscoveryError(
                f"invocation directory cannot be resolved: {invocation_directory!r}"
            ) from exc
        if not invocation.is_dir():
            raise WorkspaceDiscoveryError(f"invocation path is not a directory: {invocation}")

        declaration_path = self._nearest_declaration(invocation)
        try:
            declaration = RadixStartupAdapter(declaration_path).load_declaration()
        except StartupConfigurationError as exc:
            raise WorkspaceDiscoveryError(
                f"invalid project declaration {declaration_path}: {exc}"
            ) from exc

        project = declaration["project"]
        configured_root = Path(str(project.get("root", "."))).expanduser()
        if not configured_root.is_absolute():
            configured_root = declaration_path.parent / configured_root
        try:
            repository_root = configured_root.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceDiscoveryError(
                f"declared repository root cannot be resolved: {configured_root}"
            ) from exc
        if not repository_root.is_dir():
            raise WorkspaceDiscoveryError(
                f"declared repository root is not a directory: {repository_root}"
            )

        # A declaration found above cwd may name that directory (the normal
        # case) or an ancestor containing both. It may not redirect authority
        # to a sibling or unrelated tree.
        if not self._within(invocation, repository_root):
            raise WorkspaceDiscoveryError(
                "invocation directory is outside the declared repository root"
            )
        if not self._within(declaration_path, repository_root):
            raise WorkspaceDiscoveryError(
                "project declaration is outside the declared repository root"
            )

        project_id = str(project["id"])
        if expected_project_id is not None and project_id != expected_project_id:
            raise ProjectContextMismatchError(
                f"resolved project {project_id!r} does not match expected project "
                f"{expected_project_id!r}"
            )

        digest = hashlib.sha256(declaration_path.read_bytes()).hexdigest()
        workspace_id = hashlib.sha256(
            f"{project_id}\0{repository_root}".encode("utf-8")
        ).hexdigest()
        return WorkspaceBinding(
            project_id=project_id,
            repository_root=repository_root,
            declaration_path=declaration_path,
            invocation_directory=invocation,
            workspace_id=f"sha256:{workspace_id}",
            declaration_digest=f"sha256:{digest}",
        )

    def _nearest_declaration(self, invocation: Path) -> Path:
        for directory in (invocation, *invocation.parents):
            candidate = directory / self.declaration_name
            if candidate.is_file():
                return candidate.resolve(strict=True)
        raise WorkspaceDiscoveryError(
            f"no {self.declaration_name} found from {invocation} to filesystem root"
        )

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True


class WorkspaceBoundRadix:
    """Resolve workspace authority before compiling any startup context."""

    def __init__(
        self,
        invocation_directory: str | Path,
        *,
        expected_project_id: str | None = None,
        repository_intelligence: RepositoryIntelligence | None = None,
        session_brief: SessionBrief | None = None,
        runtime_history: RuntimeHistory | None = None,
        allowed_external_roots: tuple[str | Path, ...] = (),
    ) -> None:
        self.binding = WorkspaceResolver().discover(
            invocation_directory,
            expected_project_id=expected_project_id,
        )
        self.adapter = RadixStartupAdapter(
            self.binding.declaration_path,
            repository_intelligence=repository_intelligence,
            session_brief=session_brief,
            runtime_history=runtime_history,
            allowed_external_roots=allowed_external_roots,
        )

    def resolve_startup(
        self,
        *,
        session_id: str,
        agent: str,
        current_objective: str | None = None,
        active_phase: str | None = None,
    ) -> StartupResolution:
        resolution = self.adapter.resolve_startup(
            session_id=session_id,
            agent=agent,
            current_objective=current_objective,
            active_phase=active_phase,
        )
        provenance = dict(resolution.provenance)
        provenance["workspace_binding"] = self.binding.to_dict()
        if resolution.context is not None:
            self.binding.require_context(resolution.context)
        return StartupResolution(
            context=resolution.context,
            ready=resolution.ready,
            execution_allowed=resolution.execution_allowed,
            blocking_reasons=resolution.blocking_reasons,
            provenance=provenance,
        )
