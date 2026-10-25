"""Bounded Core Radix transport for Orca orchestration.

Orca is treated as an execution/worktree transport. Radix startup resolution
and the Core phase authority remain authoritative. This module intentionally
uses argv-based subprocess calls and never invokes a shell.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence


class OrcaOrchestrationError(ValueError):
    """Raised when Orca cannot safely accept a bounded dispatch."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")
_AGENT = re.compile(r"[a-z][a-z0-9_-]{0,31}")


@dataclass(frozen=True)
class OrchestrationDispatch:
    """Controller-bound result of one run/task/worker dispatch."""

    run_id: str
    task_id: str
    worker_id: str
    evidence_path: Path
    statuses: Mapping[str, str]


Runner = Callable[..., subprocess.CompletedProcess[str]]


class OrcaOrchestrationClient:
    """Call the installed Orca CLI with validated, non-shell argv."""

    def __init__(
        self,
        executable: str = "orca-ide",
        *,
        runner: Runner = subprocess.run,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not executable.strip() or Path(executable).name != executable:
            raise OrcaOrchestrationError("Orca CLI must be a command name, not a path or empty value")
        if timeout_seconds <= 0:
            raise OrcaOrchestrationError("Orca command timeout must be positive")
        self.executable = executable
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    def dispatch(
        self,
        *,
        project_id: str,
        repository_root: Path,
        session_id: str,
        agent: str,
        objective: str,
        task_spec: str,
        task_title: str,
        run_id: str | None = None,
        worker_name: str | None = None,
        worktree: str = "new-child",
        setup: str = "run",
        evidence_path: Path,
        environment: Mapping[str, str] | None = None,
    ) -> OrchestrationDispatch:
        self._required_text(project_id, "project id")
        self._required_text(session_id, "session id")
        self._required_text(objective, "orchestration objective")
        self._required_text(task_spec, "orchestration task specification")
        self._required_text(task_title, "orchestration task title")
        if not _AGENT.fullmatch(agent):
            raise OrcaOrchestrationError("orchestration agent identifier is invalid")
        if worktree not in {"new-child", "new-top-level"}:
            raise OrcaOrchestrationError("orchestration worktree must be new-child or new-top-level")
        if setup not in {"run", "skip", "inherit"}:
            raise OrcaOrchestrationError("orchestration setup must be run, skip or inherit")
        if run_id is not None and not _IDENTIFIER.fullmatch(run_id):
            raise OrcaOrchestrationError("orchestration run identifier is invalid")
        worker_name = worker_name or f"radix-{session_id}"
        self._required_text(worker_name, "orchestration worker name")

        env = dict(os.environ if environment is None else environment)
        responses: dict[str, Mapping[str, Any]] = {}
        commands: list[list[str]] = []
        if run_id is None:
            run_response, run_command = self._call(
                "run-create",
                "--objective",
                objective,
                environment=env,
            )
            responses["run"] = run_response
            commands.append(run_command)
            run_id = self._stage_identifier(run_response, "run")
        else:
            run_response, run_command = self._call(
                "run-show",
                "--id",
                run_id,
                environment=env,
            )
            responses["run"] = run_response
            commands.append(run_command)
            resolved_run = self._stage_identifier(run_response, "run")
            if resolved_run != run_id:
                raise OrcaOrchestrationError("Orca returned a different run identity")

        task_response, task_command = self._call(
            "task-create",
            "--spec",
            task_spec,
            "--task-title",
            task_title,
            "--run",
            run_id,
            environment=env,
        )
        responses["task"] = task_response
        commands.append(task_command)
        task_id = self._stage_identifier(task_response, "task")

        worker_response, worker_command = self._call(
            "worker-start",
            "--task",
            task_id,
            "--worktree",
            worktree,
            "--agent",
            agent,
            "--name",
            worker_name,
            "--repo",
            f"path:{repository_root}",
            "--setup",
            setup,
            "--run",
            run_id,
            environment=env,
        )
        responses["worker"] = worker_response
        commands.append(worker_command)
        worker_id = self._stage_identifier(worker_response, "worker dispatch")

        record = {
            "schema": "radix-orchestration-dispatch.v1",
            "project_id": project_id,
            "repository_root": str(repository_root),
            "session_id": session_id,
            "agent": agent,
            "objective": objective,
            "task_spec": task_spec,
            "task_title": task_title,
            "run_id": run_id,
            "task_id": task_id,
            "worker_id": worker_id,
            "worktree": worktree,
            "worker_name": worker_name,
            "setup": setup,
            "orca_cli": self.executable,
            "commands": commands,
            "responses": {
                name: {
                    "status": str(value.get("status", "unknown")),
                    "stage": value.get("stage"),
                }
                for name, value in responses.items()
            },
        }
        self._write_evidence(evidence_path, record)
        return OrchestrationDispatch(
            run_id=run_id,
            task_id=task_id,
            worker_id=worker_id,
            evidence_path=evidence_path,
            statuses={
                name: str(value.get("status", "unknown"))
                for name, value in responses.items()
            },
        )

    def _call(
        self,
        command: str,
        *arguments: str,
        environment: Mapping[str, str],
    ) -> tuple[dict[str, Any], list[str]]:
        argv = [self.executable, "orchestration", command, *arguments, "--json"]
        try:
            completed = self._runner(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env=dict(environment),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OrcaOrchestrationError(f"Orca {command} transport failed: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "transport rejected request").strip()
            raise OrcaOrchestrationError(f"Orca {command} rejected the request: {detail[:500]}")
        try:
            value = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise OrcaOrchestrationError(f"Orca {command} returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise OrcaOrchestrationError(f"Orca {command} returned a non-object response")
        return value, argv

    @staticmethod
    def _required_text(value: str, label: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise OrcaOrchestrationError(f"{label} is required")

    @classmethod
    def _identifier(cls, value: Mapping[str, Any], keys: Sequence[str], label: str) -> str:
        found = cls._find(value, keys)
        if not isinstance(found, str) or not _IDENTIFIER.fullmatch(found):
            raise OrcaOrchestrationError(f"Orca {label} identity is missing or unsafe")
        return found

    @classmethod
    def _stage_identifier(cls, value: Mapping[str, Any], stage: str) -> str:
        """Extract the domain identity, never the transport envelope ID.

        Orca responses carry a request/envelope ``id`` beside the domain
        object. The previous recursive fallback accepted that envelope ID for
        run-create, so task-create received an unresolvable run identity. Each
        stage now accepts only its documented domain object or an explicitly
        named domain-ID field; a missing or ambiguous shape fails closed.
        """

        paths: dict[str, tuple[tuple[str, ...], ...]] = {
            "run": (
                ("result", "run", "id"),
                ("run", "id"),
                ("result", "run_id"),
                ("result", "runId"),
                ("run_id",),
                ("runId",),
            ),
            "task": (
                ("result", "task", "id"),
                ("task", "id"),
                ("result", "task_id"),
                ("result", "taskId"),
                ("task_id",),
                ("taskId",),
            ),
            "worker dispatch": (
                ("result", "dispatch", "dispatch_id"),
                ("result", "dispatch", "dispatchId"),
                ("result", "worker", "id"),
                ("dispatch", "dispatch_id"),
                ("dispatch", "dispatchId"),
                ("result", "dispatch_id"),
                ("result", "dispatchId"),
                ("result", "worker_id"),
                ("result", "workerId"),
                ("worker_id",),
                ("workerId",),
                ("dispatch_id",),
                ("dispatchId",),
            ),
        }
        found = [candidate for path in paths[stage] if (candidate := cls._path_value(value, path)) is not None]
        if len(found) != 1 or not isinstance(found[0], str) or not _IDENTIFIER.fullmatch(found[0]):
            raise OrcaOrchestrationError(
                f"Orca {stage} identity is missing or unsafe (missing or ambiguous)"
            )
        return found[0]

    @staticmethod
    def _path_value(value: Mapping[str, Any], path: Sequence[str]) -> Any:
        current: Any = value
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
        return current

    @classmethod
    def _find(cls, value: Any, keys: Sequence[str]) -> Any:
        if isinstance(value, Mapping):
            for key in keys:
                if key in value:
                    return value[key]
            for child in value.values():
                found = cls._find(child, keys)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find(child, keys)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _write_evidence(path: Path, record: Mapping[str, Any]) -> None:
        if path.exists() and path.is_symlink():
            raise OrcaOrchestrationError("orchestration evidence path must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
