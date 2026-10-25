"""Resolve a project declaration into ``agent-startup-context.v1``.

This module owns platform-neutral declaration resolution only. Provider
prompt rendering and project-specific source conventions remain outside this
adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .capabilities import CapabilitySelectionError, resolve_capabilities
from .governance import GovernanceContextError, load_governance_record
from ..founder_acceptance_session import FounderAcceptanceSession, FounderAcceptanceSessionError


class StartupConfigurationError(ValueError):
    """Raised when a project declaration cannot produce startup context."""


@dataclass(frozen=True)
class StartupResolution:
    """Readiness result around, but not inside, ``agent-startup-context.v1``."""

    context: dict[str, Any] | None
    ready: bool
    execution_allowed: bool
    blocking_reasons: tuple[str, ...]
    provenance: dict[str, Any]


RepositoryIntelligence = Callable[[Path, str | None], dict[str, Any]]
SessionBrief = Callable[[Path], dict[str, Any]]
RuntimeHistory = Callable[[Path], dict[str, Any]]

# GFM task-list convention (`- [ ] ...`), not a project-specific format.
_OPEN_TASK_RE = re.compile(r"^\s*-\s*\[ \]\s*(.+?)\s*$")
_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _first_open_task(text: str) -> str | None:
    for line in text.splitlines():
        match = _OPEN_TASK_RE.match(line)
        if match:
            return match.group(1)
    return None


class RadixStartupAdapter:
    """Compile one ``development-platform.v1`` declaration into startup context."""

    schema = "agent-startup-context.v1"
    platform_schema = "development-platform.v1"

    def __init__(
        self,
        declaration_path: str | Path,
        *,
        repository_intelligence: RepositoryIntelligence | None = None,
        session_brief: SessionBrief | None = None,
        runtime_history: RuntimeHistory | None = None,
        allowed_external_roots: Iterable[str | Path] = (),
    ) -> None:
        self.declaration_path = Path(declaration_path).resolve()
        self._repository_intelligence = repository_intelligence or self._default_repository_intelligence
        self._session_brief_override = session_brief
        self._runtime_history_override = runtime_history
        self._allowed_external_roots = tuple(Path(path).resolve() for path in allowed_external_roots)

    def load_declaration(self) -> dict[str, Any]:
        try:
            declaration = yaml.safe_load(self.declaration_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise StartupConfigurationError(f"cannot read project declaration: {exc}") from exc
        if not isinstance(declaration, dict):
            raise StartupConfigurationError("project declaration must be a YAML object")
        if declaration.get("schema") != self.platform_schema:
            raise StartupConfigurationError(
                f"unsupported project declaration schema: {declaration.get('schema')!r}"
            )
        self._require_mapping(declaration, "project")
        self._validate_declaration_types(declaration)
        project_id = declaration["project"].get("id")
        if not isinstance(project_id, str) or not _PROJECT_ID_RE.fullmatch(project_id):
            raise StartupConfigurationError("project.id must match ^[a-z0-9][a-z0-9-]*$")
        self._require_mapping(declaration, "repository_intelligence")
        self._require_mapping(declaration, "agents")
        if any(not isinstance(enabled, bool) for enabled in declaration["agents"].values()):
            raise StartupConfigurationError("agents values must be boolean")
        return declaration

    @classmethod
    def _validate_declaration_types(cls, declaration: dict[str, Any]) -> None:
        allowed = {
            "schema", "project", "repository_intelligence", "agents", "gsd",
            "capabilities_manifest", "governance", "acceptance_session", "session_brief", "runtime_history", "forge", "herdr", "runtime", "batch",
        }
        cls._reject_unknown(declaration, allowed, "declaration")
        if "capabilities_manifest" in declaration:
            cls._require_string(declaration, "capabilities_manifest", "declaration")
        if "governance" in declaration:
            governance = declaration["governance"]
            if not isinstance(governance, dict):
                raise StartupConfigurationError("governance must be a YAML object")
            cls._reject_unknown(governance, {"required", "context_path", "context_digest"}, "governance")
            cls._require_bool(governance, "required", "governance")
            cls._require_string(governance, "context_path", "governance")
            digest = governance.get("context_digest")
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise StartupConfigurationError("governance.context_digest must be sha256:<64 lowercase hex>")
        if "acceptance_session" in declaration:
            session = declaration["acceptance_session"]
            if not isinstance(session, dict):
                raise StartupConfigurationError("acceptance_session must be a YAML object")
            cls._reject_unknown(session, {"required", "context_path", "context_digest"}, "acceptance_session")
            cls._require_bool(session, "required", "acceptance_session")
            cls._require_string(session, "context_path", "acceptance_session")
            digest = session.get("context_digest")
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise StartupConfigurationError("acceptance_session.context_digest must be sha256:<64 lowercase hex>")

        project = declaration["project"]
        cls._reject_unknown(project, {"id", "root", "knowledge_root", "planning_root"}, "project")
        cls._require_string(project, "id", "project")
        for field in ("root", "knowledge_root", "planning_root"):
            if field in project:
                cls._require_string(project, field, "project")

        intelligence = declaration["repository_intelligence"]
        cls._reject_unknown(
            intelligence,
            {"enabled", "provider", "freshness_policy", "degraded_mode"},
            "repository_intelligence",
        )
        cls._require_bool(intelligence, "enabled", "repository_intelligence")
        for field in ("provider", "freshness_policy", "degraded_mode"):
            if field in intelligence:
                cls._require_string(intelligence, field, "repository_intelligence")

        agents = declaration["agents"]
        for name, enabled in agents.items():
            if not isinstance(name, str) or not isinstance(enabled, bool):
                raise StartupConfigurationError("agents keys must be strings and values must be boolean")

        optional_shapes = {
            "gsd": ({"enabled", "session_governance", "planning_root", "task_authority"}, {"enabled"}),
            "session_brief": ({"enabled", "source_documents", "output_path"}, {"enabled"}),
            "runtime_history": ({"enabled", "database_path"}, {"enabled"}),
            "forge": ({"enabled", "verification", "manifest"}, {"enabled"}),
            "herdr": ({"enabled", "lifecycle_transport"}, {"enabled"}),
            "runtime": ({"enabled"}, {"enabled"}),
            "batch": ({"enabled"}, {"enabled"}),
        }
        boolean_fields = {"enabled", "lifecycle_transport"}
        for section, (fields, required) in optional_shapes.items():
            value = declaration.get(section)
            if value is None:
                continue
            if not isinstance(value, dict):
                raise StartupConfigurationError(f"{section} must be a YAML object")
            cls._reject_unknown(value, fields, section)
            for field in required:
                cls._require_bool(value, field, section)
            for field in fields - required:
                if field not in value:
                    continue
                if field == "source_documents":
                    sources = value[field]
                    if not isinstance(sources, list) or any(not isinstance(source, str) for source in sources):
                        raise StartupConfigurationError("session_brief.source_documents must be a string list")
                elif field in boolean_fields:
                    cls._require_bool(value, field, section)
                else:
                    cls._require_string(value, field, section)

    @staticmethod
    def _reject_unknown(value: dict[str, Any], allowed: set[str], section: str) -> None:
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise StartupConfigurationError(f"unknown {section} field(s): {', '.join(unknown)}")

    @staticmethod
    def _require_string(value: dict[str, Any], field: str, section: str) -> None:
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise StartupConfigurationError(f"{section}.{field} must be a non-empty string")

    @staticmethod
    def _require_bool(value: dict[str, Any], field: str, section: str) -> None:
        if not isinstance(value.get(field), bool):
            raise StartupConfigurationError(f"{section}.{field} must be boolean")

    def _path_allowed(self, path: Path, repository_root: Path) -> bool:
        candidates = (repository_root, self.declaration_path.parent, *self._allowed_external_roots)
        return any(self._is_within(path, root) for root in candidates)

    def _path_kind(self, path: Path, repository_root: Path) -> str:
        if self._is_within(path, repository_root):
            return "canonical"
        if any(self._is_within(path, root) for root in self._allowed_external_roots):
            return "external_permitted"
        return "unavailable"

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    def build_context(
        self,
        *,
        session_id: str,
        current_objective: str | None = None,
        active_phase: str | None = None,
    ) -> dict[str, Any]:
        if not session_id:
            raise StartupConfigurationError("session_id is required")
        declaration = self.load_declaration()
        project = declaration["project"]
        repository_root = _resolve_path(self.declaration_path.parent, str(project.get("root", ".")))
        knowledge_root = _resolve_path(repository_root, str(project.get("knowledge_root", ".")))
        planning_root = _resolve_path(repository_root, str(project.get("planning_root", ".")))
        governance = self._load_governance(declaration, repository_root)
        acceptance_session = self._load_acceptance_session(declaration, repository_root)
        try:
            capabilities = resolve_capabilities(
                repository_root,
                str(project["id"]),
                str(declaration.get("capabilities_manifest", ".development-platform/capabilities.yaml")),
            )
        except CapabilitySelectionError as exc:
            raise StartupConfigurationError(str(exc)) from exc
        if current_objective is None:
            current_objective = self._derive_current_objective(declaration, repository_root)
        intelligence_config = declaration["repository_intelligence"]
        provider_name = intelligence_config.get("provider")
        if intelligence_config.get("enabled") and not provider_name:
            raise StartupConfigurationError(
                "repository_intelligence.provider is required when repository intelligence is enabled"
            )
        if intelligence_config.get("enabled") and provider_name != "code-review-graph":
            raise StartupConfigurationError(f"unsupported repository intelligence provider: {provider_name!r}")

        intelligence = (
            self._repository_intelligence(repository_root, current_objective)
            if intelligence_config.get("enabled")
            else self._disabled_repository_intelligence()
        )
        session_brief_config = declaration.get("session_brief")
        session_brief_enabled = isinstance(session_brief_config, dict) and session_brief_config.get("enabled")
        if not session_brief_enabled:
            session_brief_context = self._disabled_session_brief()
        elif self._session_brief_override is not None:
            session_brief_context = self._session_brief_override(repository_root)
        else:
            session_brief_context = self._default_session_brief(session_brief_config, knowledge_root)

        runtime_history_config = declaration.get("runtime_history")
        runtime_history_enabled = isinstance(runtime_history_config, dict) and runtime_history_config.get("enabled")
        if not runtime_history_enabled:
            runtime_history_context = self._disabled_runtime_history()
        elif self._runtime_history_override is not None:
            runtime_history_context = self._runtime_history_override(repository_root)
        else:
            runtime_history_context = self._default_runtime_history(runtime_history_config, repository_root)
        return {
            "schema": self.schema,
            "project_id": str(project["id"]),
            "repository_root": str(repository_root),
            "knowledge_root": str(knowledge_root),
            "planning_root": str(planning_root),
            "current_objective": current_objective,
            "active_phase": active_phase,
            "session": {"session_id": session_id},
            "gsd_session": {
                "schema": "gsd-session-governance.v1",
                "session_id": session_id,
                "lifecycle_state": "CONTEXT_LOADED",
                "intent_status": "REQUIRED",
                "objective": current_objective,
                "profile": None,
                # Radix resolves context but does not own the session clock;
                # GSD Master appends lifecycle events when it enters each
                # state. Keeping this empty also makes identical resolutions
                # deterministic.
                "lifecycle_events": [],
            },
            "governance": self._governance_summary(governance),
            "acceptance_session": acceptance_session,
            "repository_intelligence": intelligence,
            "agents": {str(name): bool(enabled) for name, enabled in declaration["agents"].items()},
            "capabilities": capabilities,
            "session_brief": session_brief_context,
            "runtime_history": runtime_history_context,
        }

    def resolve_startup(
        self,
        *,
        session_id: str,
        agent: str,
        current_objective: str | None = None,
        active_phase: str | None = None,
    ) -> StartupResolution:
        """Resolve startup context and fail closed when execution prerequisites are missing.

        Readiness is deliberately an adapter result rather than a field on the
        frozen ``agent-startup-context.v1`` payload.
        """

        blocking: list[str] = []
        try:
            declaration = self.load_declaration()
        except StartupConfigurationError:
            return self._blocked("declaration")

        project = declaration["project"]
        repository_root = _resolve_path(self.declaration_path.parent, str(project.get("root", ".")))
        knowledge_root = _resolve_path(repository_root, str(project.get("knowledge_root", ".")))
        planning_root = _resolve_path(repository_root, str(project.get("planning_root", ".")))
        governance_config = declaration.get("governance")
        acceptance_session_config = declaration.get("acceptance_session")
        provenance: dict[str, Any] = {
            "declaration_path": str(self.declaration_path),
            "declaration_schema": declaration.get("schema"),
            "project_id": project.get("id"),
            "resolved_paths": {
                "repository_root": str(repository_root),
                "knowledge_root": str(knowledge_root),
                "planning_root": str(planning_root),
            },
            "path_kinds": {
                "repository_root": self._path_kind(repository_root, repository_root),
                "knowledge_root": self._path_kind(knowledge_root, repository_root),
                "planning_root": self._path_kind(planning_root, repository_root),
            },
            "sources": [],
            "blocking_reasons": [],
            "session_id": session_id,
        }
        governance = None
        if isinstance(governance_config, dict) and governance_config.get("required") is True:
            try:
                governance_path = _resolve_path(repository_root, str(governance_config["context_path"]))
                provenance["governance_context_path"] = str(governance_path)
                if not self._path_allowed(governance_path, repository_root):
                    blocking.append("path_policy")
                governance = load_governance_record(
                    governance_path,
                    project_id=str(project["id"]),
                    repository_root=repository_root,
                )
                if governance["provenance"]["record_digest"] != governance_config["context_digest"]:
                    raise GovernanceContextError("declaration governance.context_digest does not match context")
            except (GovernanceContextError, KeyError, OSError) as exc:
                provenance["governance_error"] = str(exc)
                blocking.append("governance_context")
        acceptance_session = None
        if isinstance(acceptance_session_config, dict) and acceptance_session_config.get("required") is True:
            try:
                session_path = _resolve_path(repository_root, str(acceptance_session_config["context_path"]))
                provenance["acceptance_session_context_path"] = str(session_path)
                if not self._path_allowed(session_path, repository_root):
                    blocking.append("path_policy")
                acceptance_session = FounderAcceptanceSession(session_path).load()
                if acceptance_session["digest"] != acceptance_session_config["context_digest"]:
                    raise FounderAcceptanceSessionError("declaration acceptance_session.context_digest does not match context")
                if acceptance_session["status"] != "OPEN":
                    raise FounderAcceptanceSessionError("acceptance session is not open")
            except (FounderAcceptanceSessionError, KeyError, OSError) as exc:
                provenance["acceptance_session_error"] = str(exc)
                blocking.append("acceptance_session")
        repository_root_allowed = any(
            self._is_within(repository_root, root)
            for root in (self.declaration_path.parent, *self._allowed_external_roots)
        )
        if not repository_root_allowed or not all(
            self._path_allowed(path, repository_root) for path in (knowledge_root, planning_root)
        ):
            blocking.append("path_policy")
        if not all(path.is_dir() for path in (repository_root, knowledge_root, planning_root)):
            blocking.append("canonical_roots")

        gsd = declaration.get("gsd")
        task_text = ""
        if not isinstance(gsd, dict) or not gsd.get("enabled") or not gsd.get("task_authority"):
            blocking.append("task_authority")
        else:
            task_path = _resolve_path(repository_root, str(gsd["task_authority"]))
            provenance["task_authority_path"] = str(task_path)
            if not self._path_allowed(task_path, repository_root):
                blocking.append("path_policy")
            try:
                task_text = task_path.read_text(encoding="utf-8")
            except OSError:
                blocking.append("task_authority")

        task = _first_open_task(task_text) if task_text else None
        if task is None:
            blocking.append("task")
        objective = task
        if current_objective is not None and current_objective.strip() != (task or ""):
            blocking.append("objective")
        if not isinstance(objective, str) or not objective.strip():
            blocking.append("objective")
        provenance["objective"] = {"source": "task_authority", "value": objective}

        if agent not in declaration["agents"] or not declaration["agents"].get(agent):
            blocking.append("agent")

        session_brief = declaration.get("session_brief")
        if isinstance(session_brief, dict) and session_brief.get("enabled"):
            source_documents = session_brief.get("source_documents") or []
            for source in source_documents:
                source_path = (knowledge_root / source).resolve()
                provenance["sources"].append({"path": str(source_path), "kind": "canonical"})
                if not self._path_allowed(source_path, repository_root) or not source_path.is_file():
                    blocking.append("required_source")

            output_path = (knowledge_root / (session_brief.get("output_path") or "session-brief.md")).resolve()
            if not self._path_allowed(output_path, repository_root):
                blocking.append("path_policy")

        runtime_history = declaration.get("runtime_history")
        if isinstance(runtime_history, dict) and runtime_history.get("enabled"):
            database_path = _resolve_path(repository_root, str(runtime_history.get("database_path") or ".runtime/store.db"))
            provenance["sources"].append({"path": str(database_path), "kind": "canonical"})
            if not self._path_allowed(database_path, repository_root):
                blocking.append("path_policy")

        intelligence_config = declaration["repository_intelligence"]
        intelligence: dict[str, Any]
        if intelligence_config.get("enabled"):
            provider_name = intelligence_config.get("provider")
            if not provider_name or provider_name != "code-review-graph":
                blocking.append("declaration")
                intelligence = self._disabled_repository_intelligence()
            else:
                try:
                    intelligence = self._repository_intelligence(repository_root, objective)
                except Exception:
                    blocking.append("repository_state")
                    intelligence = self._disabled_repository_intelligence()
        else:
            intelligence = self._disabled_repository_intelligence()

        trusted = intelligence.get("trusted") is True
        degraded_allowed = intelligence_config.get("degraded_mode") == "startup-without-trusted-context"
        if not trusted and not degraded_allowed:
            blocking.append("repository_state")

        context: dict[str, Any] | None = None
        if not blocking:
            try:
                context = self.build_context(
                    session_id=session_id,
                    current_objective=objective,
                    active_phase=active_phase,
                )
                if acceptance_session is not None:
                    context["acceptance_session"] = acceptance_session
            except StartupConfigurationError:
                blocking.append("declaration")

        if context is not None:
            if context["session_brief"]["status"] == "unavailable" and isinstance(session_brief, dict) and session_brief.get("enabled"):
                blocking.append("required_source")

        provenance["repository_intelligence"] = {
            "provider": intelligence.get("provider"),
            "status": intelligence.get("status"),
            "trusted": intelligence.get("trusted") is True,
            "degraded_mode": intelligence_config.get("degraded_mode"),
        }
        provenance["blocking_reasons"] = list(dict.fromkeys(blocking))
        if blocking:
            return self._blocked(*dict.fromkeys(blocking), provenance=provenance)
        return StartupResolution(
            context=context,
            ready=True,
            execution_allowed=True,
            blocking_reasons=(),
            provenance=provenance,
        )

    def _load_governance(self, declaration: dict[str, Any], repository_root: Path) -> dict[str, Any] | None:
        config = declaration.get("governance")
        if not isinstance(config, dict) or not config.get("required"):
            return None
        path = _resolve_path(repository_root, str(config["context_path"]))
        record = load_governance_record(
            path,
            project_id=str(declaration["project"]["id"]),
            repository_root=repository_root,
        )
        if record["provenance"]["record_digest"] != config["context_digest"]:
            raise StartupConfigurationError("declaration governance.context_digest does not match context")
        return record

    @staticmethod
    def _load_acceptance_session(
        declaration: dict[str, Any], repository_root: Path
    ) -> dict[str, Any] | None:
        config = declaration.get("acceptance_session")
        if not isinstance(config, dict) or not config.get("required"):
            return None
        path = _resolve_path(repository_root, str(config["context_path"]))
        session = FounderAcceptanceSession(path).load()
        if session["digest"] != config["context_digest"]:
            raise StartupConfigurationError(
                "declaration acceptance_session.context_digest does not match context"
            )
        if session["status"] != "OPEN":
            raise StartupConfigurationError("acceptance session is not open")
        return session

    @staticmethod
    def _governance_summary(record: dict[str, Any] | None) -> dict[str, Any] | None:
        if record is None:
            return None
        return {
            "schema": record["schema"],
            "context_id": record["context_id"],
            "status": record["status"],
            "owner": record["owner"],
            "mandate": record["mandate"],
            "authority": record["authority"],
            "review": record["review"],
            "approval_policy": record["approval_policy"],
            "delegations": record.get("delegations", []),
            "record_digest": record["provenance"]["record_digest"],
        }

    @staticmethod
    def _blocked(*reasons: str, provenance: dict[str, Any] | None = None) -> StartupResolution:
        unique = tuple(dict.fromkeys(reason for reason in reasons if reason))
        return StartupResolution(
            context=None,
            ready=False,
            execution_allowed=False,
            blocking_reasons=unique,
            provenance=provenance or {"blocking_reasons": list(unique)},
        )

    @staticmethod
    def _require_mapping(declaration: dict[str, Any], name: str) -> None:
        if not isinstance(declaration.get(name), dict):
            raise StartupConfigurationError(f"project declaration field {name!r} must be a YAML object")

    @staticmethod
    def _derive_current_objective(declaration: dict[str, Any], repository_root: Path) -> str | None:
        """Derive the objective from the declaration's own gsd.task_authority
        document — no project-specific filename or path is assumed. Fails
        closed (returns None) rather than guessing when gsd is disabled,
        unset, or the file can't be read."""
        gsd = declaration.get("gsd")
        if not isinstance(gsd, dict) or not gsd.get("enabled"):
            return None
        task_authority = gsd.get("task_authority")
        if not task_authority:
            return None
        task_path = _resolve_path(repository_root, str(task_authority))
        try:
            text = task_path.read_text(encoding="utf-8")
        except OSError:
            return None
        return _first_open_task(text)

    @staticmethod
    def _default_repository_intelligence(
        repository_root: Path, objective: str | None
    ) -> dict[str, Any]:
        from providers.repository_intelligence import RepositoryIntelligenceProvider

        return RepositoryIntelligenceProvider(repository_root).collect_context(objective)

    @staticmethod
    def _disabled_repository_intelligence() -> dict[str, Any]:
        return {
            "schema": "repository-intelligence.v1",
            "status": "UNAVAILABLE",
            "provider": "disabled",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "indexed_revision": None,
            "trusted": False,
            "relevant_files": [],
            "relevant_symbols": [],
            "notes": ["Repository intelligence is disabled by project configuration."],
            "freshness_evidence": [],
        }

    @staticmethod
    def _disabled_session_brief() -> dict[str, Any]:
        return {
            "status": "unavailable",
            "path": None,
            "reason": "session brief is disabled by project configuration",
        }

    @staticmethod
    def _default_session_brief(session_brief_config: dict[str, Any], knowledge_root: Path) -> dict[str, Any]:
        from providers.session_brief import SessionBriefProvider

        source_documents = session_brief_config.get("source_documents") or []
        output_path = session_brief_config.get("output_path") or "session-brief.md"
        provider = SessionBriefProvider(
            knowledge_root=knowledge_root, source_documents=source_documents, output_path=output_path
        )
        return provider.ensure()

    @staticmethod
    def _disabled_runtime_history() -> dict[str, Any]:
        return {
            "status": "unavailable",
            "recent_runs": [],
            "reason": "runtime history is disabled by project configuration",
        }

    @staticmethod
    def _default_runtime_history(runtime_history_config: dict[str, Any], repository_root: Path) -> dict[str, Any]:
        from providers.runtime_history import RuntimeHistoryProvider

        database_path = runtime_history_config.get("database_path") or ".runtime/store.db"
        resolved = _resolve_path(repository_root, str(database_path))
        return RuntimeHistoryProvider(database_path=resolved).collect()
