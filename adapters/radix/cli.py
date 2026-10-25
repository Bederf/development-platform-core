"""Core-owned, workspace-aware interactive Radix command.

This command resolves authority exclusively from ``development-platform.yaml``
through Core's existing startup adapter, then replaces itself with the selected
interactive agent in the authoritative repository root. It never reads a
consumer-owned launcher, vault, task queue, or provider wrapper.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence, TextIO

from ..agent_adapter import AgentAdapter, AgentAdapterError
from providers.working_state import WorkingStateError
from .context_projection import ContextProjectionError, StartupContextProjector
from .gsd_projection import GsdProjectionError, verify_codex_projection, write_launch_attestation
from ..gsd_phase_resolver import (
    GsdPhaseResolutionError,
    resolve_authoritative_dpc_phase,
    resolve_authoritative_project_phase,
)
from .workspace import WorkspaceBoundRadix, WorkspaceDiscoveryError
from .pipeline import PipelineError, create_run, validate_pipeline_definition
from .orchestration import OrcaOrchestrationError, OrcaOrchestrationClient


Executor = Callable[[str, list[str], dict[str, str]], object]
ExecutableResolver = Callable[..., str | None]
DirectoryChanger = Callable[[str], object]

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class RadixCLIError(ValueError):
    """Raised when the interactive gateway cannot establish a safe launch."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radix",
        description="Resolve Core project authority and launch an interactive agent.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Invocation directory; the nearest development-platform.yaml owns authority.",
    )
    parser.add_argument("--session-id", help="Stable session identifier for automation.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--agent", help="Enabled agent identifier and executable name.")
    selection.add_argument("--runtime", dest="agent", help="Alias for --agent.")
    selection.add_argument("--codex", dest="agent", action="store_const", const="codex")
    selection.add_argument("--claude", dest="agent", action="store_const", const="claude")
    selection.add_argument("--opencode", dest="agent", action="store_const", const="opencode")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and print; do not execute.")
    parser.add_argument(
        "--orchestrate",
        action="store_true",
        help="Dispatch one bounded worker through the existing Orca orchestration transport.",
    )
    parser.add_argument("--orchestration-objective", help="Objective for a new Orca run; defaults to Radix startup objective.")
    parser.add_argument("--orchestration-spec", help="Explicit task specification for the Orca worker.")
    parser.add_argument("--orchestration-task-title", help="Concise Orca task title.")
    parser.add_argument("--orchestration-run", help="Existing Orca run identifier to reuse.")
    parser.add_argument("--orchestration-worker-name", help="Optional Orca worker/worktree name.")
    parser.add_argument(
        "--orchestration-worktree",
        choices=("new-child", "new-top-level"),
        default="new-child",
        help="Isolated Orca worktree mode (default: new-child).",
    )
    parser.add_argument(
        "--orchestration-setup",
        choices=("run", "skip", "inherit"),
        default="run",
        help="Orca repository setup policy (default: run).",
    )
    parser.add_argument(
        "--orca-cli",
        help="Orca CLI command name; defaults to ORCA_CLI_COMMAND or orca-ide.",
    )
    parser.add_argument(
        "--phase",
        help="DPC phase number to resolve through the authoritative planning root before launch.",
    )
    parser.add_argument(
        "--working-state-input",
        type=Path,
        help="Optional validated derived working-state checkpoint for the separate startup projection.",
    )
    parser.add_argument(
        "--working-state-gsd",
        type=Path,
        help="Authoritative GSD JSON used to validate or regenerate WorkingState.",
    )
    parser.add_argument(
        "--working-state-session-records",
        type=Path,
        help="Authoritative session-record JSON array used to validate or regenerate WorkingState.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable dry-run output.")
    parser.add_argument(
        "--allow-external-root",
        action="append",
        default=[],
        metavar="PATH",
        help="Explicitly permit a declared knowledge/planning root outside the repository (repeatable).",
    )
    parser.add_argument(
        "agent_args",
        nargs=argparse.REMAINDER,
        help="Arguments after -- are passed unchanged to the selected agent.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    which: ExecutableResolver = shutil.which,
    executor: Executor = os.execvpe,
    chdir: DirectoryChanger = os.chdir,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv and raw_argv[0] == "init":
        from .init_cli import main as init_main

        return init_main(raw_argv[1:], stdout=stdout or sys.stdout, stdin=stdin)
    if raw_argv and raw_argv[0] == "pipeline":
        return _pipeline_main(raw_argv[1:], stdout=stdout or sys.stdout, stderr=stderr or sys.stderr)
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    args = build_parser().parse_args(raw_argv)
    environment = dict(os.environ if environ is None else environ)

    try:
        agent = _agent(args.agent)
        session_id = _session(args.session_id)
        workspace = WorkspaceBoundRadix(
            args.project,
            allowed_external_roots=tuple(args.allow_external_root),
        )
        resolution = workspace.resolve_startup(
            session_id=session_id,
            agent=agent,
            active_phase=args.phase,
        )
        if not resolution.ready or not resolution.execution_allowed or resolution.context is None:
            reasons = ", ".join(resolution.blocking_reasons) or "startup authority unresolved"
            raise RadixCLIError(f"startup blocked: {reasons}")
        try:
            agent_request = AgentAdapter().build(
                agent=agent,
                request_id=f"agent.{session_id}",
                startup_context=resolution.context,
                mode="interactive",
            ).to_dict()
        except AgentAdapterError as exc:
            raise RadixCLIError(f"agent request rejected: {exc}") from exc

        repository_root = workspace.binding.repository_root
        phase_resolution = None
        if args.phase is not None:
            try:
                planning_root = resolution.context.get("planning_root")
                if not isinstance(planning_root, str) or not planning_root.strip():
                    raise RadixCLIError("phase authority rejected: planning root is unavailable")
                phase_resolver = (
                    resolve_authoritative_dpc_phase
                    if workspace.binding.project_id == "development-platform-core"
                    else resolve_authoritative_project_phase
                )
                phase_resolution = phase_resolver(
                    workspace.binding.project_id,
                    repository_root,
                    planning_root,
                    args.phase,
                )
            except (GsdPhaseResolutionError, OSError) as exc:
                raise RadixCLIError(f"phase authority rejected: {exc}") from exc
        executable = which(agent, path=environment.get("PATH"))
        if not executable:
            raise RadixCLIError(f"agent executable is unavailable on PATH: {agent}")
        executable = str(Path(executable).expanduser().resolve())
        context_path = _context_path(repository_root, session_id)
        projection_path = None
        if args.working_state_input is not None:
            if args.working_state_gsd is None or args.working_state_session_records is None:
                raise RadixCLIError(
                    "working-state recovery requires --working-state-gsd and "
                    "--working-state-session-records"
                )
            projection_path = _working_state_projection(
                args.working_state_input,
                repository_root=repository_root,
                project_id=workspace.binding.project_id,
                context=resolution.context,
                session_id=session_id,
                gsd_path=args.working_state_gsd,
                session_records_path=args.working_state_session_records,
            )
        provider_args = list(args.agent_args)
        if provider_args and provider_args[0] == "--":
            provider_args = provider_args[1:]
        if agent == "codex":
            provider_args = _codex_startup_arguments(provider_args, context_path)

        gsd_projection = None
        if agent == "codex":
            capabilities = resolution.context.get("capabilities", {})
            selections = capabilities.get("selections") if isinstance(capabilities, dict) else None
            gsd = selections.get("gsd") if isinstance(selections, dict) else None
            if isinstance(gsd, dict) and gsd.get("enabled") is True:
                try:
                    gsd_projection = verify_codex_projection(
                        project_root=repository_root,
                        capability=gsd,
                        agent_args=provider_args,
                        environ=environment,
                    )
                except GsdProjectionError as exc:
                    raise RadixCLIError(str(exc)) from exc

        plan = {
            "project_id": workspace.binding.project_id,
            "repository_root": str(repository_root),
            "workspace_id": workspace.binding.workspace_id,
            "declaration_path": str(workspace.binding.declaration_path),
            "session_id": session_id,
            "agent": agent,
            "executable": executable,
            "arguments": provider_args,
            "startup_context_file": str(context_path),
            "startup_projection_file": str(projection_path) if projection_path else None,
            "agent_request": agent_request,
            "phase": (
                {
                    "phase_id": phase_resolution.phase_id,
                    "specification_id": phase_resolution.specification_id,
                    "specification_version": phase_resolution.specification_version,
                    "specification_hash": phase_resolution.specification_hash,
                    "markdown_path": str(phase_resolution.markdown_path),
                    "specification_path": str(phase_resolution.specification_path),
                }
                if phase_resolution is not None
                else None
            ),
            "gsd_projection": gsd_projection,
            "herdr": {
                "enabled": environment.get("HERDR_ENV") == "1",
                "pane_id": environment.get("HERDR_PANE_ID"),
            },
            "orchestrate": args.orchestrate,
        }

        if args.orchestrate:
            objective = args.orchestration_objective or str(resolution.context.get("current_objective") or "")
            task_spec = args.orchestration_spec or objective
            task_title = args.orchestration_task_title or f"Radix {agent} worker"
            if not task_spec.strip():
                raise RadixCLIError("--orchestrate requires --orchestration-spec or a startup objective")
            plan["orchestration"] = {
                "objective": objective,
                "task_spec": task_spec,
                "task_title": task_title,
                "run_id": args.orchestration_run,
                "worker_name": args.orchestration_worker_name,
                "worktree": args.orchestration_worktree,
                "setup": args.orchestration_setup,
                "orca_cli": args.orca_cli or environment.get("ORCA_CLI_COMMAND") or "orca-ide",
            }

        if args.dry_run:
            _print_plan(plan, as_json=args.json, output=output)
            return 0

        _write_context(context_path, resolution.context)
        attestation_path = None
        if gsd_projection is not None:
            try:
                attestation_path = write_launch_attestation(
                    project_root=repository_root,
                    session_id=session_id,
                    project_id=workspace.binding.project_id,
                    projection=gsd_projection,
                )
            except OSError as exc:
                raise RadixCLIError(f"cannot persist GSD projection attestation: {exc}") from exc
        launch_environment = _launch_environment(
            environment,
            plan=plan,
            attestation_path=attestation_path,
        )
        if args.orchestrate:
            orchestration = plan["orchestration"]
            evidence_path = repository_root / ".runtime" / "radix" / "sessions" / session_id / "orchestration-dispatch.json"
            try:
                dispatch = OrcaOrchestrationClient(
                    str(orchestration["orca_cli"]),
                ).dispatch(
                    project_id=workspace.binding.project_id,
                    repository_root=repository_root,
                    session_id=session_id,
                    agent=agent,
                    objective=str(orchestration["objective"]),
                    task_spec=str(orchestration["task_spec"]),
                    task_title=str(orchestration["task_title"]),
                    run_id=orchestration["run_id"],
                    worker_name=orchestration["worker_name"],
                    worktree=str(orchestration["worktree"]),
                    setup=str(orchestration["setup"]),
                    evidence_path=evidence_path,
                    environment=environment,
                )
            except OrcaOrchestrationError as exc:
                raise RadixCLIError(str(exc)) from exc
            plan["orchestration_result"] = {
                "run_id": dispatch.run_id,
                "task_id": dispatch.task_id,
                "worker_id": dispatch.worker_id,
                "evidence_path": str(dispatch.evidence_path),
                "statuses": dict(dispatch.statuses),
            }
            _print_plan(plan, as_json=args.json, output=output)
            return 0
        chdir(str(repository_root))
        executor(executable, [executable, *provider_args], launch_environment)
        return 0
    except (OSError, RadixCLIError, WorkspaceDiscoveryError) as exc:
        print("RADIX_READY=false", file=errors)
        print("RADIX_EXECUTION_ALLOWED=false", file=errors)
        print(str(exc), file=errors)
        return 2


def _pipeline_main(argv: Sequence[str], *, stdout: TextIO, stderr: TextIO) -> int:
    """Validate a plan and emit a review-only run; never execute a provider."""

    parser = argparse.ArgumentParser(prog="radix pipeline")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    try:
        pipeline = json.loads(args.plan.read_text(encoding="utf-8"))
        digest = validate_pipeline_definition(pipeline)
        run = create_run(pipeline, source_revision=args.source_revision, run_id=args.run_id)
        result = {"status": "review_only_ready", "pipeline_digest": digest, "run": run}
    except (OSError, json.JSONDecodeError, PipelineError) as exc:
        print(f"RADIX_PIPELINE_BLOCKED={exc}", file=stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True), file=stdout)
    else:
        print("RADIX_PIPELINE_STATUS=review_only_ready", file=stdout)
        print(f"RADIX_PIPELINE_DIGEST={digest}", file=stdout)
        print(f"RADIX_PIPELINE_RUN_ID={run['run_id']}", file=stdout)
    return 0


def _agent(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", value):
        raise RadixCLIError("agent identifier is invalid")
    return value


def _session(value: object) -> str:
    if value is None:
        value = "radix-%s-%d" % (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            os.getpid(),
        )
    if not isinstance(value, str) or not _SESSION_ID.fullmatch(value):
        raise RadixCLIError("session-id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    return value


def _context_path(repository_root: Path, session_id: str) -> Path:
    return repository_root / ".runtime" / "radix" / "sessions" / session_id / "startup-context.json"


def _codex_startup_arguments(provider_args: list[str], context_path: Path) -> list[str]:
    """Give Codex an explicit first-turn instruction to load Radix context.

    ``RADIX_STARTUP_CONTEXT_FILE`` is useful to subprocesses, but environment
    variables are not conversation input. Codex accepts one positional initial
    prompt, so place the instruction after an argument separator and preserve
    all caller-supplied options unchanged.
    """
    prompt = (
        "Before doing any work, read the authoritative Radix startup context at "
        f"{context_path}. Treat it as the startup authority for this session; "
        "use its project, repository root, objective, capabilities, and governance "
        "constraints to orient yourself. Confirm that it was loaded, then proceed."
    )
    return [*provider_args, "--", prompt]


def _working_state_projection(
    checkpoint_path: Path,
    *,
    repository_root: Path,
    project_id: str,
    context: Mapping[str, object],
    session_id: str,
    gsd_path: Path,
    session_records_path: Path,
) -> Path:
    from providers.working_state import WorkingStateProvider

    try:
        checkpoint_bytes = checkpoint_path.read_bytes()
        checkpoint = json.loads(checkpoint_bytes.decode("utf-8"))
        if not isinstance(checkpoint, dict):
            raise WorkingStateError("working-state input must be an object")
        gsd = _load_authority_json(gsd_path, repository_root=repository_root, expected="object")
        session_records = _load_authority_json(
            session_records_path, repository_root=repository_root, expected="array"
        )
        recovery_path = (
            repository_root / ".runtime" / "radix" / "sessions" / session_id / "working-state-recovery.json"
        )
        if checkpoint_path.expanduser().resolve() == recovery_path.resolve():
            raise WorkingStateError("working-state input cannot be the derived recovery path")
        recovery_path.parent.mkdir(parents=True, exist_ok=True)
        recovery_path.write_bytes(checkpoint_bytes)
        provider = WorkingStateProvider(
            project_id=project_id,
            checkpoint_path=recovery_path,
        )
        recovered, _status = provider.load_or_regenerate(
            gsd=gsd,
            session_records=session_records,
        )
        lineage = provider.resume_lineage(recovered, new_session_id=session_id)
        evidence = _evidence_references(session_records, repository_root=repository_root)
        projection = StartupContextProjector().project(
            project_id=project_id,
            objective=str(context.get("current_objective") or recovered["objective"]),
            tasks=[],
            brief={"status": "unavailable", "path": None, "text": None},
            sections=[],
            source_documents=[],
            working_state=recovered,
            working_state_lineage=lineage,
            evidence_references=evidence,
        )
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError, ContextProjectionError, WorkingStateError) as exc:
        raise RadixCLIError(f"working-state bridge rejected: {exc}") from exc
    path = repository_root / ".runtime" / "radix" / "sessions" / session_id / "startup-projection.json"
    _write_context(path, projection)
    return path


def _load_authority_json(path: Path, *, repository_root: Path, expected: str) -> dict | list:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(repository_root)
    except ValueError as exc:
        raise WorkingStateError("working-state authority input must be inside the repository") from exc
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if expected == "object" and not isinstance(value, dict):
        raise WorkingStateError("working-state GSD authority must be an object")
    if expected == "array" and (
        not isinstance(value, list) or any(not isinstance(item, dict) for item in value)
    ):
        raise WorkingStateError("working-state session authority must be an array of objects")
    values = [value] if isinstance(value, dict) else value
    for item in values:
        if item.get("superseded") is True or item.get("status") in {"superseded", "contradictory", "rejected"}:
            raise WorkingStateError("working-state authority is superseded or contradictory")
        contradictions = item.get("contradicts")
        if contradictions:
            raise WorkingStateError("working-state authority contains unresolved contradictions")
    return value


def _evidence_references(
    session_records: Sequence[Mapping[str, object]], *, repository_root: Path
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for record in session_records:
        raw_refs = record.get("evidence_refs", [])
        if not isinstance(raw_refs, list):
            raise ValueError("session record evidence_refs must be an array")
        for raw in raw_refs:
            if not isinstance(raw, Mapping):
                raise ValueError("session evidence reference must be an object")
            ref = raw.get("ref")
            raw_path = raw.get("path")
            if not isinstance(ref, str) or not ref.strip() or not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError("session evidence reference requires ref and path")
            path = Path(raw_path).expanduser()
            resolved = (path if path.is_absolute() else repository_root / path).resolve()
            try:
                resolved.relative_to(repository_root)
            except ValueError as exc:
                raise ValueError("session evidence path must be inside the repository") from exc
            references.append(
                {
                    "ref": ref.strip(),
                    "path": str(resolved),
                    "status": "available" if resolved.is_file() else "unavailable",
                }
            )
    return references


def _write_context(path: Path, context: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _launch_environment(
    environment: Mapping[str, str],
    *,
    plan: Mapping[str, object],
    attestation_path: Path | None = None,
) -> dict[str, str]:
    sanitized = {key: value for key, value in environment.items() if not key.startswith("RADIX_")}
    sanitized.update(
        {
            "RADIX_READY": "true",
            "RADIX_EXECUTION_ALLOWED": "true",
            "RADIX_PROJECT_ID": str(plan["project_id"]),
            "RADIX_REPOSITORY_ROOT": str(plan["repository_root"]),
            "RADIX_WORKSPACE_ID": str(plan["workspace_id"]),
            "RADIX_DECLARATION_PATH": str(plan["declaration_path"]),
            "RADIX_SESSION_ID": str(plan["session_id"]),
            "RADIX_STARTUP_CONTEXT_FILE": str(plan["startup_context_file"]),
        }
    )
    if plan.get("startup_projection_file"):
        sanitized["RADIX_STARTUP_PROJECTION_FILE"] = str(plan["startup_projection_file"])
    if attestation_path is not None:
        sanitized["RADIX_GSD_PROJECTION_ATTESTATION"] = str(attestation_path)
    return sanitized


def _print_plan(plan: Mapping[str, object], *, as_json: bool, output: TextIO) -> None:
    if as_json:
        print(json.dumps(plan, sort_keys=True), file=output)
        return
    print("RADIX_READY=true", file=output)
    print("RADIX_EXECUTION_ALLOWED=true", file=output)
    print(f"project_id: {plan['project_id']}", file=output)
    print(f"repository_root: {plan['repository_root']}", file=output)
    print(f"agent: {plan['agent']}", file=output)
    print(f"executable: {plan['executable']}", file=output)


if __name__ == "__main__":
    raise SystemExit(main())
