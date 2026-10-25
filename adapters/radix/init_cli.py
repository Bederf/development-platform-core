"""Plan-only guided project initialization for the Core-owned Radix CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence, TextIO

from jsonschema import Draft202012Validator
import yaml

from .approval import BootstrapApprovalError, verify_approval
from .capabilities import CAPABILITY_REGISTRY, PROFILE_REGISTRY, WORKFLOW_PROVIDER_REGISTRY
from .governance import GovernanceContextError, load_governance_record
from ..phase_creation import prepare_phase_creation
from ..phase_specification import calculate_specification_hash, validate_phase_specification
from .workspace import WorkspaceBoundRadix, WorkspaceDiscoveryError
from ..project_definition import ProjectDefinitionError, validate_project_definition


class RadixInitCLIError(ValueError):
    """Raised when a project initialization plan cannot be safely produced."""


_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PROFILE = re.compile(r"^([a-z0-9][a-z0-9._-]{0,63})=([a-z0-9][a-z0-9._:-]{0,127})@([0-9]+\.[0-9]+\.[0-9]+)$")
_INFISICAL_PROJECT_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_WORKFLOW_PROVIDER = re.compile(
    r"^(SPECIFICATION|ASSESSMENT|PLAN|TASKS|IMPLEMENTATION|CONVERGENCE)="
    r"(native-gsd|spec-kit)@([0-9]+\.[0-9]+\.[0-9]+)$"
)
_COMMAND_INPUT = re.compile(r"(?:^|\s)radix\s+init\b", re.IGNORECASE)
_PLAN_SCHEMA = "radix-guided-bootstrap-plan.v2"
_DEFAULT_VAULT_PATH = "knowledge-vault"
_REQUIRED_CAPABILITIES = ("security-audit",)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radix init",
        description="Create and apply an approved Core project bootstrap, including its Radix launcher.",
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--project-id")
    parser.add_argument(
        "--guided",
        action="store_true",
        help="Run the guided project-definition questions before producing the plan.",
    )
    parser.add_argument(
        "--intent",
        help="Project intent for guided decision support; it does not select technologies automatically.",
    )
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        metavar="TEXT",
        help="Project constraint for guided decision support (repeatable).",
    )
    parser.add_argument("--capability", action="append", default=[], metavar="ID")
    parser.add_argument("--profile", action="append", default=[], metavar="CAPABILITY=PROFILE@VERSION")
    parser.add_argument(
        "--workflow-provider",
        action="append",
        default=[],
        metavar="STAGE=PROVIDER@VERSION",
        help="Explicit GSD workflow provider selection (for example SPECIFICATION=spec-kit@1.0.4).",
    )
    parser.add_argument("--ocr-transport", choices=("direct", "omniroute"), default="direct")
    parser.add_argument("--infisical-project-id", help="Retained only for legacy plan compatibility.")
    parser.add_argument("--infisical-env", default="prod", help="Retained only for legacy plan compatibility.")
    parser.add_argument("--infisical-path", default="/omniroute", help="Retained only for legacy plan compatibility.")
    parser.add_argument(
        "--second-brain-vault",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Set up an Obsidian second-brain vault during approved apply (guided mode asks if omitted).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Plan path (default: PROJECT/.development-platform/radix-init-plan.json).",
    )
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing the plan artifact only.")
    parser.add_argument("--json", action="store_true", help="Emit the plan as JSON after writing it.")
    parser.add_argument("--review", type=Path, help="Review an existing plan without writing or activating anything.")
    parser.add_argument("--project-definition", type=Path, help="Canonical project-definition.v1 to validate read-only.")
    parser.add_argument("--validate-project-definition", action="store_true", help="Validate --project-definition and its governance binding without writing.")
    parser.add_argument("--apply", type=Path, help="Apply an approved plan, enable selected capabilities, and install radix.sh.")
    parser.add_argument(
        "--apply-approved",
        action="store_true",
        help="Generate this plan, verify --approval-record against its digest, then apply and validate it.",
    )
    parser.add_argument("--approve", action="store_true", help="Explicitly approve the plan for manifest generation.")
    parser.add_argument("--approval-record", type=Path, help="Versioned approval record for the plan.")
    parser.add_argument(
        "--governed", action="store_true",
        help="Require an attributable project governance context before apply and GSD startup.",
    )
    parser.add_argument(
        "--adopt", action="store_true",
        help="Reconcile an existing project's governance context instead of creating a new one.",
    )
    parser.add_argument(
        "--governance-record", type=Path,
        help="Attributable project-governance.v1 record used by governed apply.",
    )
    parser.add_argument(
        "--task-authority",
        default=".development-platform/TASKS.md",
        help="Task-authority path for guided apply (default: .development-platform/TASKS.md).",
    )
    parser.add_argument("--task", help="Initial open task for guided apply.")
    parser.add_argument("--objective", help="Initial objective for guided apply; defaults to --task.")
    parser.add_argument(
        "--create-gsd-plan",
        action="store_true",
        help="Include an approved, non-executing draft GSD architecture phase in guided apply.",
    )
    parser.add_argument(
        "--agent",
        choices=("codex", "claude", "opencode"),
        default="codex",
        help="Agent used for guided post-apply startup validation (default: codex).",
    )
    return parser


def _read_answer(stdin: TextIO) -> str:
    answer = stdin.readline()
    if answer == "":
        raise RadixInitCLIError("guided setup cancelled: end of input")
    return answer.strip()


def _questionnaire(
    *,
    project_id: str | None,
    capabilities: Sequence[str],
    intent: str | None,
    constraints: Sequence[str],
    second_brain_vault: bool | None,
    stdin: TextIO,
    stdout: TextIO,
) -> tuple[str, list[str], str, tuple[str, ...], bool]:
    """Collect intent before explicit capability decisions for human-run init."""

    print(
        "Welcome to Core guided project setup.\n"
        "I will help capture your project intent, constraints, and explicit capability decisions "
        "before creating a reviewable, non-activating bootstrap plan.\n"
        "Core will not automatically choose technologies, install software, or change your project.\n"
        "You are already inside guided setup; answer each question directly rather than entering the command again.\n",
        file=stdout,
    )

    if project_id is None:
        while True:
            print("Project ID (lowercase letters, numbers, and hyphens): ", end="", file=stdout, flush=True)
            answer = _read_answer(stdin)
            if _COMMAND_INPUT.search(answer):
                print(
                    "That looks like the shell command, which is already running. "
                    "Enter only a project ID, for example: research-system.",
                    file=stdout,
                )
                continue
            if _PROJECT_ID.fullmatch(answer):
                project_id = answer
                break
            print("Please enter a valid project ID.", file=stdout)

    if intent is None:
        while True:
            print("What are you building? ", end="", file=stdout, flush=True)
            answer = _read_answer(stdin)
            if answer:
                intent = answer
                break
            print("Please describe the project in one sentence.", file=stdout)
    elif not intent.strip():
        raise RadixInitCLIError("--intent must not be empty")

    normalized_constraints = tuple(item.strip() for item in constraints if item.strip())
    if not normalized_constraints:
        print("Constraints or preferences (optional, comma-separated): ", end="", file=stdout, flush=True)
        answer = _read_answer(stdin)
        normalized_constraints = tuple(item.strip() for item in answer.split(",") if item.strip())

    print("\nChoose explicit capabilities. Select gsd if you want guided application to validate an initial governed task. OmniRoute is optional; direct review is the default.", file=stdout)
    selected = list(dict.fromkeys((*capabilities, *_REQUIRED_CAPABILITIES)))
    print("\nSecurity audit: included in every new project as an explicit build/release capability; pre-commit and production execution remain disabled.", file=stdout)
    if not capabilities:
        print("\nOptional capabilities:", file=stdout)
        for capability in sorted(CAPABILITY_REGISTRY):
            if capability in _REQUIRED_CAPABILITIES:
                continue
            registry = CAPABILITY_REGISTRY[capability]
            print(f"  {capability} ({registry['readiness']})", file=stdout)
            while True:
                print(f"Add {capability}? [y/N]: ", end="", file=stdout, flush=True)
                answer = _read_answer(stdin).lower()
                if answer in {"", "n", "no"}:
                    break
                if answer in {"y", "yes"}:
                    selected.append(capability)
                    break
                print("Please answer y or n.", file=stdout)
    if not selected:
        raise RadixInitCLIError("at least one capability must be selected")
    # v3-only vault setup remains explicitly unpromoted. The authoritative
    # v2 questionnaire must not silently collect or activate that decision.
    if second_brain_vault is None:
        second_brain_vault = False
    return project_id, selected, intent.strip(), normalized_constraints, second_brain_vault


def main(argv: Sequence[str] | None = None, *, stdout: TextIO, stdin: TextIO | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    input_stream = stdin or sys.stdin
    try:
        if args.validate_project_definition:
            if args.project_definition is None:
                raise RadixInitCLIError("--validate-project-definition requires --project-definition")
            try:
                document = json.loads(args.project_definition.read_text(encoding="utf-8"))
                resolution = validate_project_definition(document, governance_root=args.project)
            except (OSError, json.JSONDecodeError, ProjectDefinitionError) as exc:
                raise RadixInitCLIError(f"project definition validation failed: {exc}") from exc
            result = {
                "status": "validated",
                "definition_id": resolution.definition_id,
                "project_id": resolution.project_id,
                "version": resolution.version,
                "digest": resolution.digest,
                "governance_path": str(resolution.governance_path),
            }
            if args.json:
                print(json.dumps(result, sort_keys=True), file=stdout)
            else:
                print("RADIX_PROJECT_DEFINITION_STATUS=validated", file=stdout)
                print(f"RADIX_PROJECT_DEFINITION_ID={resolution.definition_id}", file=stdout)
                print(f"RADIX_PROJECT_DEFINITION_DIGEST={resolution.digest}", file=stdout)
            return 0
        if args.apply_approved and (args.apply is not None or args.review is not None):
            raise RadixInitCLIError("--apply-approved cannot be combined with --apply or --review")
        if args.apply_approved and args.approval_record is None:
            raise RadixInitCLIError("--apply-approved requires --approval-record")
        if args.review is not None:
            result = review_plan(args.review, project=args.project, project_id=args.project_id)
            if args.json:
                print(json.dumps(result, sort_keys=True), file=stdout)
            else:
                print(f"RADIX_INIT_REVIEW={args.review.resolve()}", file=stdout)
                print("RADIX_INIT_APPROVAL_REQUIRED=true", file=stdout)
                print("RADIX_INIT_ACTIVATED=false", file=stdout)
            return 0
        if args.apply is not None:
            if not args.approve and args.approval_record is None:
                raise RadixInitCLIError("--apply requires --approve or --approval-record")
            startup_config = None
            reviewed_plan = review_plan(args.apply, project=args.project, project_id=args.project_id)
            planned_startup = reviewed_plan.get("startup")
            if args.guided or planned_startup is not None:
                planned_startup = planned_startup or {}
                startup_config = _guided_startup_config(
                    task_authority=args.task_authority or planned_startup.get("task_authority", ".development-platform/TASKS.md"),
                    task=args.task or planned_startup.get("task"),
                    objective=args.objective or planned_startup.get("objective"),
                    agent=args.agent or planned_startup.get("agent", "codex"),
                    stdin=input_stream,
                    stdout=sys.stderr if args.json else stdout,
                )
            result = apply_plan(
                args.apply,
                project=args.project,
                project_id=args.project_id,
                overwrite=args.overwrite,
                approval_path=args.approval_record,
                startup_config=startup_config,
            )
            if args.json:
                print(json.dumps(result, sort_keys=True), file=stdout)
            else:
                print(f"RADIX_INIT_MANIFEST={result['manifest_path']}", file=stdout)
                print(f"RADIX_INIT_LAUNCHER={result['launcher_path']}", file=stdout)
                if result.get("vault_path"):
                    print(f"RADIX_INIT_OBSIDIAN_VAULT={result['vault_path']}", file=stdout)
                if result.get("startup_validated"):
                    print("RADIX_INIT_STARTUP_VALIDATED=true", file=stdout)
                print("RADIX_INIT_CAPABILITIES_ENABLED=true", file=stdout)
                print("RADIX_INIT_ACTIVATED=false", file=stdout)
            return 0
        guided_context: tuple[str, tuple[str, ...]] | None = None
        startup_context: dict[str, str] | None = None
        non_interactive_guided = bool(
            args.guided
            and args.project_id
            and args.intent
            and args.task
            and args.capability
        )
        if args.guided and non_interactive_guided:
            normalized_constraints = tuple(item.strip() for item in args.constraint if item.strip())
            guided_context = (args.intent.strip(), normalized_constraints)
            startup_context = {
                "task_authority": args.task_authority,
                "task": args.task.strip(),
                "objective": (args.objective or args.task).strip(),
                "agent": args.agent,
            }
            if not guided_context[0] or not startup_context["task"] or not startup_context["objective"]:
                raise RadixInitCLIError("non-interactive guided init requires non-empty intent, task, and objective")
            if startup_context["objective"] != startup_context["task"]:
                raise RadixInitCLIError("guided startup objective must match the initial task-authority task")
        elif args.guided or args.project_id is None or not args.capability:
            if not input_stream.isatty() and stdin is None:
                raise RadixInitCLIError(
                    "interactive init requires a terminal; provide --project-id and --capability for automation"
                )
            args.project_id, args.capability, guided_intent, guided_constraints, prompted_vault = _questionnaire(
                project_id=args.project_id,
                capabilities=args.capability,
                intent=args.intent,
                constraints=args.constraint,
                second_brain_vault=args.second_brain_vault,
                stdin=input_stream,
                stdout=sys.stderr if args.json else stdout,
            )
            args.second_brain_vault = prompted_vault
            guided_context = (guided_intent, guided_constraints)
            if args.task or args.objective:
                startup_context = {
                    "task_authority": args.task_authority,
                    "task": (args.task or "").strip(),
                    "objective": (args.objective or args.task or "").strip(),
                    "agent": args.agent,
                }
        elif args.intent is not None or args.constraint:
            raise RadixInitCLIError("--intent and --constraint require --guided")
        plan = build_plan(
            project=args.project,
            project_id=args.project_id,
            capabilities=args.capability,
            profiles=args.profile,
            workflow_providers=args.workflow_provider,
            ocr_transport=args.ocr_transport,
            infisical_project_id=args.infisical_project_id,
            infisical_env=args.infisical_env,
            infisical_path=args.infisical_path,
            second_brain_vault=bool(args.second_brain_vault),
            create_gsd_plan=args.create_gsd_plan,
            governed=args.governed,
            adopt=args.adopt,
            governance_record=args.governance_record,
        )
        if guided_context is not None:
            plan["project_context"] = {"intent": guided_context[0], "constraints": list(guided_context[1])}
        if startup_context is not None:
            if not startup_context["task"] or not startup_context["objective"]:
                raise RadixInitCLIError("guided startup requires a non-empty task and objective")
            plan["startup"] = startup_context
        if args.create_gsd_plan and guided_context is None:
            raise RadixInitCLIError("--create-gsd-plan requires --guided with an explicit project intent")
        if args.create_gsd_plan and startup_context is None:
            raise RadixInitCLIError("--create-gsd-plan requires --task for the initial architecture objective")
        if args.apply_approved and startup_context is None:
            raise RadixInitCLIError("--apply-approved requires --guided with task and objective for startup validation")
        output = (args.output or (Path(args.project) / ".development-platform" / "radix-init-plan.json")).resolve()
        validate_plan(plan)
        if output.exists() and not args.overwrite:
            raise RadixInitCLIError(f"refusing to overwrite existing plan: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.apply_approved:
            result = apply_plan(
                output,
                project=args.project,
                project_id=args.project_id,
                overwrite=args.overwrite,
                approval_path=args.approval_record,
                startup_config=startup_context,
            )
            result["plan_path"] = str(output)
            result["approval_mode"] = "external-approval-record"
            if args.json:
                print(json.dumps(result, sort_keys=True), file=stdout)
            else:
                print(f"RADIX_INIT_PLAN={output}", file=stdout)
                print(f"RADIX_INIT_MANIFEST={result['manifest_path']}", file=stdout)
                print(f"RADIX_INIT_LAUNCHER={result['launcher_path']}", file=stdout)
                print("RADIX_INIT_APPROVAL_VERIFIED=true", file=stdout)
                print("RADIX_INIT_STARTUP_VALIDATED=true", file=stdout)
                print("RADIX_INIT_ACTIVATED=false", file=stdout)
            return 0
        if args.json:
            print(json.dumps(plan, sort_keys=True), file=stdout)
        else:
            if guided_context is not None:
                intent_value, constraints_value = guided_context
                print(f"RADIX_INIT_INTENT_CAPTURED={bool(intent_value)}", file=stdout)
                print(f"RADIX_INIT_CONSTRAINTS_CAPTURED={len(constraints_value)}", file=stdout)
                print("RADIX_INIT_DECISIONS_EXPLICIT=true", file=stdout)
                print("RADIX_INIT_OBSIDIAN_VAULT_SELECTED=False", file=stdout)
            print(f"RADIX_INIT_PLAN={output}", file=stdout)
            print("RADIX_INIT_ACTIVATED=false", file=stdout)
        return 0
    except (OSError, RadixInitCLIError) as exc:
        print("RADIX_INIT_READY=false", file=stdout)
        print(str(exc), file=stdout)
        return 2


def build_plan(
    *,
    project: Path,
    project_id: str,
    capabilities: Sequence[str],
    profiles: Sequence[str],
    workflow_providers: Sequence[str] = (),
    ocr_transport: str = "direct",
    infisical_project_id: str | None = None,
    infisical_env: str = "prod",
    infisical_path: str = "/omniroute",
    second_brain_vault: bool = False,
    create_gsd_plan: bool = False,
    governed: bool = False,
    adopt: bool = False,
    governance_record: Path | None = None,
) -> dict:
    project = project.expanduser().resolve()
    if not project.is_dir():
        raise RadixInitCLIError(f"project directory does not exist: {project}")
    if not _PROJECT_ID.fullmatch(project_id):
        raise RadixInitCLIError("project-id must match ^[a-z0-9][a-z0-9-]{0,63}$")
    try:
        root = Path(
            subprocess.check_output(
                ["git", "-C", str(project), "rev-parse", "--show-toplevel"], text=True
            ).strip()
        ).resolve()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RadixInitCLIError("project must be an existing Git repository") from exc
    if root != project:
        raise RadixInitCLIError("project must be the Git repository root")
    if adopt and not governed:
        raise RadixInitCLIError("--adopt requires --governed")
    if governed and governance_record is None:
        raise RadixInitCLIError("--governed requires --governance-record")
    selected = list(dict.fromkeys((*capabilities, *_REQUIRED_CAPABILITIES)))
    unknown = [capability for capability in selected if capability not in CAPABILITY_REGISTRY]
    if unknown:
        raise RadixInitCLIError(f"unsupported capability: {unknown[0]}")
    profile_map: dict[str, list[dict[str, str]]] = {capability: [] for capability in selected}
    workflow_provider_map: dict[str, dict[str, str]] = {}
    for value in workflow_providers:
        match = _WORKFLOW_PROVIDER.fullmatch(value)
        if not match:
            raise RadixInitCLIError(f"invalid workflow provider selection: {value}")
        stage, provider, version = match.groups()
        if "gsd" not in selected:
            raise RadixInitCLIError("--workflow-provider requires the gsd capability")
        registered = WORKFLOW_PROVIDER_REGISTRY.get(provider)
        if registered is None or registered["version"] != version:
            expected = registered["version"] if registered else "unsupported"
            raise RadixInitCLIError(
                f"workflow provider version does not match Core registry: {provider} (expected {expected})"
            )
        if stage in workflow_provider_map:
            raise RadixInitCLIError(f"duplicate workflow provider stage: {stage}")
        workflow_provider_map[stage] = {
            "provider": provider,
            "version": version,
            "readiness": registered["readiness"],
        }
    for value in profiles:
        match = _PROFILE.fullmatch(value)
        if not match:
            raise RadixInitCLIError(f"invalid profile selection: {value}")
        capability, profile_id, version = match.groups()
        if capability not in profile_map:
            raise RadixInitCLIError(f"profile capability is not selected: {capability}")
        registered = PROFILE_REGISTRY.get(profile_id)
        if registered is None:
            raise RadixInitCLIError(f"unsupported capability profile: {profile_id}")
        if registered["base_capability"] != capability:
            raise RadixInitCLIError(f"capability profile base does not match selection: {profile_id}")
        if registered["version"] != version:
            raise RadixInitCLIError(f"capability profile version does not match Core registry: {profile_id}")
        profile_map[capability].append({"id": profile_id, "version": version})
    selections = []
    for capability in sorted(selected):
        registry = CAPABILITY_REGISTRY[capability]
        selections.append(
            {
                "capability": capability,
                "enabled": True,
                "implementation": registry["implementation"],
                "version": registry["version"],
                "profiles": profile_map[capability],
                **({"configuration": {"workflow_providers": workflow_provider_map}} if capability == "gsd" and workflow_provider_map else {}),
                **({"configuration": {"execution": "explicit-build-release", "pre_commit": "disabled", "production": "disabled"}} if capability == "security-audit" else {}),
            }
        )
    plan = {
        "schema": _PLAN_SCHEMA,
        "plan_id": "radix-guided-bootstrap",
        "project_id": project_id,
        "repository_root": str(project),
        "selections": selections,
        "application_effects": [
            "Create/update declaration and selected capabilities",
            "Enable selected capabilities after explicit approval",
            "Install a project-local radix.sh launcher",
            *(["Create an Obsidian-compatible second-brain vault and preserve existing notes"] if second_brain_vault else []),
            "Install project skills while preserving existing skill files",
            "Install owned commit checks and push-only optional AI review hooks",
            "Set core.hooksPath after checking for existing hook conflicts",
            "Write quality configuration and selection-aware documentation",
            "Guided apply creates task authority and planning directories",
            "Provider credentials and live availability require separate verification",
            *( ["Project governance context is required and must be confirmed or reconciled before GSD startup"] if governed else []),
        ],
        "generated_artifacts": [
            "development-platform.yaml",
            ".development-platform/capabilities.yaml",
            "radix.sh",
            *( [".development-platform/governance.json"] if governed else []),
            *([f"{_DEFAULT_VAULT_PATH}/Home.md", f"{_DEFAULT_VAULT_PATH}/00-Inbox.md", f"{_DEFAULT_VAULT_PATH}/Projects/Projects.md", f"{_DEFAULT_VAULT_PATH}/Reference/Reference.md"] if second_brain_vault else []),
        ],
        "limitations": [
            "No capability is activated or bound",
            "Plan-only: files and capabilities are applied only after explicit approval",
            "Selected capabilities are enabled at apply time; provider credentials and live availability require separate verification",
            "Requirements, candidates, and policy decisions remain external inputs",
            "Guided intent and constraints are retained as project context; explicit capability selections remain the plan decisions",
        ],
    }
    if governed:
        plan["governance"] = {
            "required": True,
            "mode": "adopt" if adopt else "new",
            "record_path": str(governance_record.expanduser().resolve()),
        }
    if second_brain_vault:
        raise RadixInitCLIError(
            "second-brain vault selection requires the unpromoted radix-guided-bootstrap-plan.v3"
        )
    if ocr_transport == "omniroute":
        plan["review_transport"] = {
            "ocr": {
                "transport": "omniroute",
                "infisical_project_id": infisical_project_id,
                "infisical_env": infisical_env,
                "infisical_path": infisical_path,
            }
        }
    if create_gsd_plan:
        if "gsd" not in selected:
            raise RadixInitCLIError("--create-gsd-plan requires the gsd capability")
        plan["planning"] = {"create_gsd_architecture_draft": True}
        plan["application_effects"].append(
            "Create a draft GSD architecture phase after approved startup validation; do not execute it automatically"
        )
        plan["limitations"].append(
            "The generated GSD architecture phase is a draft requiring owner review and approval before implementation"
        )
    return plan


def validate_plan(plan: dict) -> None:
    """Validate the guided artifact before it crosses the filesystem boundary."""

    schema_version = plan.get("schema") if isinstance(plan, dict) else None
    if schema_version not in {"radix-guided-bootstrap-plan.v1", "radix-guided-bootstrap-plan.v2", "radix-guided-bootstrap-plan.v3"}:
        raise RadixInitCLIError("unsupported guided bootstrap plan schema")
    schema_path = Path(__file__).resolve().parents[2] / "contracts" / f"{schema_version}.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RadixInitCLIError(f"cannot read guided bootstrap plan schema: {schema_path}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(plan), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "document"
        raise RadixInitCLIError(f"invalid guided bootstrap plan at {location}: {errors[0].message}")


def review_plan(plan_path: Path, *, project: Path, project_id: str | None) -> dict:
    """Read and verify a guided plan without changing project state."""

    plan_path = plan_path.expanduser().resolve()
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RadixInitCLIError(f"cannot read review plan: {plan_path}") from exc
    if not isinstance(plan, dict):
        raise RadixInitCLIError("review plan must be a JSON object")
    validate_plan(plan)
    project = project.expanduser().resolve()
    if plan["repository_root"] != str(project):
        raise RadixInitCLIError("review plan repository_root does not match project")
    if project_id is not None and plan["project_id"] != project_id:
        raise RadixInitCLIError("review plan project_id does not match --project-id")
    return {
        "schema": "radix-guided-bootstrap-review.v1",
        "plan_schema": plan["schema"],
        "plan_path": str(plan_path),
        "project_id": plan["project_id"],
        "repository_root": plan["repository_root"],
        "selections": plan["selections"],
        "generated_artifacts": plan["generated_artifacts"],
        "review_transport": plan.get("review_transport"),
        "second_brain_vault": plan.get("second_brain_vault", {"enabled": False, "path": None}),
        "project_context": plan.get("project_context"),
        "governance": plan.get("governance"),
        "startup": plan.get("startup"),
        "planning": plan.get("planning", {"create_gsd_architecture_draft": False}),
        "application_effects": plan.get("application_effects", ["Application installs quality hooks, skills, configuration and documentation"]),
        "approval_required": True,
        "activated": False,
    }


def _guided_startup_config(
    *,
    task_authority: str,
    task: str | None,
    objective: str | None,
    agent: str,
    stdin: TextIO,
    stdout: TextIO,
) -> dict[str, str]:
    """Collect the minimum governed state needed for post-apply startup validation."""

    authority = task_authority.strip()
    if not authority:
        raise RadixInitCLIError("--task-authority must not be empty")
    if task is None:
        print("Task/objective for the first governed agent session: ", end="", file=stdout, flush=True)
        task = _read_answer(stdin)
    if not task or not task.strip():
        raise RadixInitCLIError("guided apply requires a non-empty task/objective")
    task = task.strip()
    objective = (objective or task).strip()
    if not objective:
        raise RadixInitCLIError("guided apply requires a non-empty objective")
    return {
        "task_authority": authority,
        "task": task,
        "objective": objective,
        "agent": agent,
    }


def _create_gsd_architecture_draft(
    *,
    project: Path,
    project_id: str,
    project_context: dict[str, Any] | None,
    startup_config: dict[str, str],
    planning_root: Path,
) -> dict[str, str]:
    """Create a validated, non-executing first GSD architecture phase."""

    if not project_context or not project_context.get("intent"):
        raise RadixInitCLIError("GSD architecture draft requires explicit project intent")
    existing_numbers = []
    for candidate in planning_root.glob("Phase-*.md"):
        match = re.match(r"Phase-(\d+)-", candidate.name)
        if match:
            existing_numbers.append(int(match.group(1)))
    number = max(existing_numbers, default=0) + 1
    phase_label = f"{number:03d}"
    phase_id = f"P{phase_label}"
    slug = "MVP-Architecture"
    title = "MVP Architecture"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    intent = str(project_context["intent"]).strip()
    constraints = [str(item).strip() for item in project_context.get("constraints", []) if str(item).strip()]
    spec: dict[str, Any] = {
        "schema": "phase-specification.v1",
        "phase": {
            "specification_id": f"{project_id}-mvp-architecture",
            "phase_id": phase_id,
            "title": title,
            "version": "1.0.0",
            "specification_hash": "",
            "created_at": now,
            "updated_at": now,
            "created_by": "radix:init",
            "provenance": {
                "source_refs": [
                    "radix-project-context",
                    "radix-startup-task",
                    "GSD-MASTER-GLOBAL-ONE-SHOT-ORCHESTRATION-POLICY-v1.1",
                ],
                "supersedes_ref": None,
            },
            "workflow": {"schema": "development-workflow.v1", "workflow_id": None},
        },
        "intent": {
            "objective": startup_config["objective"],
            "desired_outcome": f"A reviewed MVP architecture and implementation plan for {project_id}.",
            "business_context": intent,
        },
        "scope": {
            "in_scope": ["Clarify MVP users, workflows, domain boundaries and success criteria", "Produce a reviewable architecture and implementation plan"],
            "non_goals": ["Application implementation", "Deployment, release or production authority", "Automatic approval of the architecture"],
            "constraints": constraints,
        },
        "requirements": [
            {
                "requirement_id": f"{phase_id}-R001",
                "statement": "Define the MVP intent, users, workflows and acceptance boundaries.",
                "mandatory": True,
                "acceptance_criteria": [{"criterion_id": f"{phase_id}-C001", "statement": "The architecture phase records explicit users, workflows, constraints and measurable acceptance criteria."}],
                "evidence_contract": [{"evidence_type": "mvp-intent-record", "required": True, "producer": "gsd:master", "verification_method": "owner review"}],
                "verification_method": "Review the captured project intent and resulting architecture brief.",
                "dependencies": [],
            },
            {
                "requirement_id": f"{phase_id}-R002",
                "statement": "Produce an architecture and implementation plan consistent with the approved intent.",
                "mandatory": True,
                "acceptance_criteria": [{"criterion_id": f"{phase_id}-C002", "statement": "The plan identifies components, interfaces, data boundaries, risks, verification and deferred decisions."}],
                "evidence_contract": [{"evidence_type": "mvp-architecture-plan", "required": True, "producer": "gsd:master", "verification_method": "independent architecture review"}],
                "verification_method": "Review the architecture plan against the project intent and constraints.",
                "dependencies": [f"{phase_id}-R001"],
            },
            {
                "requirement_id": f"{phase_id}-R003",
                "statement": "Keep architecture discovery separate from implementation authorization.",
                "mandatory": True,
                "acceptance_criteria": [{"criterion_id": f"{phase_id}-C003", "statement": "No application code is generated and implementation remains blocked until the owner approves a subsequent implementation phase."}],
                "evidence_contract": [{"evidence_type": "architecture-boundary-review", "required": True, "producer": "development-platform-core.independent-review", "verification_method": "read-only boundary review"}],
                "verification_method": "Inspect generated artifacts and the phase gate for absence of implementation authority.",
                "dependencies": [f"{phase_id}-R002"],
            },
        ],
        "implementation": {
            "tasks": [
                {"task_id": f"{phase_id}-T001", "statement": "Capture MVP intent, users, workflows, constraints and acceptance criteria.", "depends_on": [], "requirement_refs": [f"{phase_id}-R001"], "expected_artifacts": ["mvp-intent-record"]},
                {"task_id": f"{phase_id}-T002", "statement": "Create the reviewable MVP architecture and implementation plan.", "depends_on": [f"{phase_id}-T001"], "requirement_refs": [f"{phase_id}-R002"], "expected_artifacts": ["mvp-architecture-plan"]},
                {"task_id": f"{phase_id}-T003", "statement": "Review the architecture boundary and record owner decisions; do not implement application code.", "depends_on": [f"{phase_id}-T002"], "requirement_refs": [f"{phase_id}-R003"], "expected_artifacts": ["architecture-boundary-review"]},
            ],
            "execution_strategy": "One admitted phase executes its dependency graph continuously through one review boundary. This architecture phase does not implement application code; implementation requires a separately approved follow-on phase.",
        },
        "verification": {
            "required_checks": ["phase-specification.v1 validation", "owner review of project intent", "architecture boundary review", "changed-file scope review"],
            "required_evidence": ["mvp-intent-record", "mvp-architecture-plan", "architecture-boundary-review"],
            "forge_required": False,
            "live_verification_required": False,
        },
        "independent_review": {
            "required": True,
            "authority": "development-platform-core.independent-review",
            "required_context": ["phase-specification", "project-context", "architecture-plan"],
            "required_evidence": ["architecture-boundary-review"],
            "remediation_on_findings": "Return to architecture discovery for requirement or boundary findings; implementation defects are not in scope.",
        },
        "convergence": {
            "required": True,
            "required_conditions": ["phase specification validates", "architecture plan is reviewable", "implementation remains separately gated", "independent review passes"],
            "failure_states": ["REMEDIATION_REQUIRED", "BLOCKED"],
        },
        "remediation": {
            "retry_policy": "Bounded correction cycles for architecture artefact defects only.",
            "rework_policy": "Return to intent capture when requirements or boundaries are unresolved.",
            "escalation_policy": "Escalate unresolved authority, security, data or production decisions to the owner before implementation planning continues.",
        },
        "acceptance": {
            "authority": "development-platform-core.acceptance-authority",
            "workflow_schema": "development-workflow.v1",
            "required_conditions": ["intent and architecture evidence present", "independent review passes", "no application code generated", "follow-on implementation authorization remains separate", "separate phase acceptance decision is recorded"],
        },
    }
    spec["phase"]["specification_hash"] = calculate_specification_hash(spec)
    try:
        validate_phase_specification(spec)
    except Exception as exc:
        raise RadixInitCLIError(f"generated GSD architecture specification is invalid: {exc}") from exc
    phase_path = planning_root / f"Phase-{phase_label}-{slug}.md"
    spec_path = planning_root / f"Phase-{phase_label}-{slug}.specification.json"
    if phase_path.exists() or spec_path.exists():
        raise RadixInitCLIError(f"refusing to overwrite existing GSD architecture phase {phase_label}")
    phase_path.write_text(
        f"---\nphase: {phase_id}\nversion: 1.0.0\nlast_updated: {now[:10]}\nstatus: DRAFT\n---\n\n"
        f"# Phase {phase_label} — {title}\n\n"
        "## Problem Statement\n\n"
        f"Define the architecture for the first governed MVP of `{project_id}` from the captured intent: {intent}\n\n"
        "## Acceptance Criteria\n\n"
        "- [ ] MVP users, workflows, constraints and success criteria are explicit.\n"
        "- [ ] Architecture and implementation boundaries are reviewable.\n"
        "- [ ] No application code is implemented by this phase.\n\n"
        "## Dependencies\n\n"
        "### Codebase\n\n"
        "The project declaration, capability manifest and task authority created by Radix.\n\n"
        "## Phase Gate\n\n"
        "gate_type: owner-review\nmin_phase: architecture\nfailure_action: REMEDIATION_REQUIRED\n\n"
        "## Trade-offs\n\n"
        "- Not doing application implementation in the architecture phase.\n"
        "- Not granting deployment, release or production authority.\n\n"
        "## Next Steps\n\n"
        "Review and approve the architecture before creating an implementation phase.\n",
        encoding="utf-8",
    )
    spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    preparation_path = planning_root / f"Phase-{phase_label}-{slug}.preparation.json"
    try:
        prepare_phase_creation(
            specification_path=spec_path,
            markdown_path=phase_path,
            evidence_path=planning_root / f"Phase-{phase_label}-{slug}.run.json",
            preparation_path=preparation_path,
        )
    except Exception as exc:
        phase_path.unlink(missing_ok=True)
        spec_path.unlink(missing_ok=True)
        preparation_path.unlink(missing_ok=True)
        raise RadixInitCLIError(f"generated GSD phase one-shot preparation failed: {exc}") from exc
    return {
        "phase_path": str(phase_path),
        "specification_path": str(spec_path),
        "preparation_path": str(preparation_path),
        "phase_id": phase_id,
    }


def apply_plan(
    plan_path: Path,
    *,
    project: Path,
    project_id: str | None,
    overwrite: bool,
    approval_path: Path | None = None,
    startup_config: dict[str, str] | None = None,
) -> dict:
    """Materialize an approved plan and its Core-owned quality-layer integration."""

    reviewed = review_plan(plan_path, project=project, project_id=project_id)
    project = project.expanduser().resolve()
    governance_record: dict[str, Any] | None = None
    governance_target = _resolve_project_path(project, ".development-platform/governance.json")
    if (reviewed.get("governance") or {}).get("required"):
        source = Path(reviewed["governance"]["record_path"]).expanduser().resolve()
        try:
            governance_record = load_governance_record(
                source,
                project_id=reviewed["project_id"],
                repository_root=project,
            )
        except GovernanceContextError as exc:
            raise RadixInitCLIError(f"governance context verification failed: {exc}") from exc
        if reviewed["governance"]["mode"] == "adopt" and governance_record["status"] != "reconciled":
            raise RadixInitCLIError("--adopt requires a governance context with status reconciled")
        if reviewed["governance"]["mode"] == "new" and governance_record["status"] != "confirmed":
            raise RadixInitCLIError("new governed initialization requires a governance context with status confirmed")
    approval_verified = False
    if approval_path is not None:
        try:
            approval = json.loads(approval_path.expanduser().resolve().read_text(encoding="utf-8"))
            plan = json.loads(plan_path.expanduser().resolve().read_text(encoding="utf-8"))
            schema_path = Path(__file__).resolve().parents[2] / "contracts" / "bootstrap-approval.v1.schema.json"
            approval_schema = json.loads(schema_path.read_text(encoding="utf-8"))
            verify_approval(plan=plan, approval=approval, schema=approval_schema)
        except (OSError, json.JSONDecodeError, BootstrapApprovalError) as exc:
            raise RadixInitCLIError(f"bootstrap approval verification failed: {exc}") from exc
        approval_verified = True
    try:
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/install-quality-hooks.py"), "--project", str(project), "--check"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RadixInitCLIError(exc.stderr.strip() or "quality initialization preflight failed") from exc
    if startup_config and not any(selection["capability"] == "gsd" for selection in reviewed["selections"]):
        raise RadixInitCLIError("guided startup requires selecting gsd; use non-guided apply for capability-only setup")
    manifest = _resolve_project_path(project, ".development-platform/capabilities.yaml")
    declaration = _resolve_project_path(project, "development-platform.yaml")
    if (reviewed.get("governance") or {}).get("mode") == "adopt" and not declaration.exists():
        raise RadixInitCLIError("governance adoption requires an existing development-platform.yaml")
    if not declaration.exists() and not os.access(project, os.W_OK):
        raise RadixInitCLIError(
            f"project root is not writable; cannot create declaration: {project}"
        )
    if manifest.exists() and not overwrite:
        raise RadixInitCLIError(f"refusing to overwrite existing capability manifest: {manifest}")
    capabilities: dict[str, dict] = {}
    for selection in reviewed["selections"]:
        entry = {
            "enabled": selection["enabled"],
            "implementation": selection["implementation"],
            "version": selection["version"],
        }
        if selection["profiles"]:
            entry["profiles"] = selection["profiles"]
        if selection.get("configuration"):
            entry["configuration"] = selection["configuration"]
        if selection["capability"] == "ocr" and reviewed.get("review_transport"):
            entry["configuration"] = {"review_transport": reviewed["review_transport"]}
        capabilities[selection["capability"]] = entry
    vault_selected = reviewed["second_brain_vault"]["enabled"]
    snapshots = _snapshot_paths((manifest, declaration, governance_target)) if startup_config or vault_selected or governance_record else {}
    task_authority_path: Path | None = None
    task_snapshot: tuple[bool, bytes | None] | None = None
    planning_root: Path | None = None
    generated_phase_paths: list[Path] = []
    try:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            yaml.safe_dump(
                {"schema": "development-capability-selection.v1", "project_id": reviewed["project_id"], "capabilities": capabilities},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        if governance_record is not None:
            governance_target.parent.mkdir(parents=True, exist_ok=True)
            governance_target.write_text(json.dumps(governance_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        declaration_created = not declaration.exists()
        if startup_config:
            if declaration_created:
                declaration_data: dict[str, Any] = {
                    "schema": "development-platform.v1",
                    "capabilities_manifest": ".development-platform/capabilities.yaml",
                    "project": {
                        "id": reviewed["project_id"],
                        "root": ".",
                        "knowledge_root": (reviewed["second_brain_vault"]["path"] if reviewed["second_brain_vault"]["enabled"] else "."),
                        "planning_root": ".development-platform/gsd-phases",
                    },
                    "repository_intelligence": {"enabled": False, "degraded_mode": "startup-without-trusted-context"},
                    "agents": {"claude": True, "codex": True, "opencode": True},
                    "gsd": {"enabled": False},
                    "session_brief": {"enabled": False},
                    "runtime_history": {"enabled": False},
                }
            else:
                try:
                    declaration_data = yaml.safe_load(declaration.read_text(encoding="utf-8"))
                except (OSError, yaml.YAMLError) as exc:
                    raise RadixInitCLIError(f"cannot read project declaration: {exc}") from exc
                if not isinstance(declaration_data, dict):
                    raise RadixInitCLIError("project declaration must be a YAML object")
                declaration_data = deepcopy(declaration_data)
            if governance_record is not None:
                declaration_data["governance"] = {
                    "required": True,
                    "context_path": ".development-platform/governance.json",
                    "context_digest": governance_record["provenance"]["record_digest"],
                }
            _apply_startup_configuration(
                declaration_data,
                project_id=reviewed["project_id"],
                startup_config=startup_config,
            )
            if vault_selected:
                declaration_data["project"]["knowledge_root"] = reviewed["second_brain_vault"]["path"]
            task_authority_path = _resolve_project_path(project, startup_config["task_authority"])
            task_snapshot = _snapshot_path(task_authority_path)
            if not task_authority_path.exists():
                task_authority_path.parent.mkdir(parents=True, exist_ok=True)
                task_authority_path.write_text(f"- [ ] {startup_config['task']}\n", encoding="utf-8")
            planning_root = _resolve_project_path(project, str(declaration_data["gsd"]["planning_root"]))
            planning_root.mkdir(parents=True, exist_ok=True)
            declaration.write_text(yaml.safe_dump(declaration_data, sort_keys=False), encoding="utf-8")
        elif governance_record is not None:
            if declaration_created:
                declaration.write_text(
                    yaml.safe_dump(
                        {
                            "schema": "development-platform.v1",
                            "capabilities_manifest": ".development-platform/capabilities.yaml",
                            "project": {"id": reviewed["project_id"], "root": ".", "knowledge_root": ".", "planning_root": "."},
                            "governance": {"required": True, "context_path": ".development-platform/governance.json", "context_digest": governance_record["provenance"]["record_digest"]},
                            "repository_intelligence": {"enabled": False, "degraded_mode": "startup-without-trusted-context"},
                            "agents": {"claude": True, "codex": True, "opencode": True},
                            "gsd": {"enabled": False},
                            "session_brief": {"enabled": False},
                            "runtime_history": {"enabled": False},
                        },
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
            else:
                try:
                    declaration_data = yaml.safe_load(declaration.read_text(encoding="utf-8"))
                except (OSError, yaml.YAMLError) as exc:
                    raise RadixInitCLIError(f"cannot read project declaration: {exc}") from exc
                if not isinstance(declaration_data, dict):
                    raise RadixInitCLIError("project declaration must be a YAML object")
                declaration_data = deepcopy(declaration_data)
                declaration_data["governance"] = {
                    "required": True,
                    "context_path": ".development-platform/governance.json",
                    "context_digest": governance_record["provenance"]["record_digest"],
                }
                declaration.write_text(yaml.safe_dump(declaration_data, sort_keys=False), encoding="utf-8")
        elif declaration_created:
            declaration.write_text(
                "\n".join(
                    [
                        "schema: development-platform.v1",
                        "capabilities_manifest: .development-platform/capabilities.yaml",
                        "project:",
                        f"  id: {reviewed['project_id']}",
                        "  root: .",
                        f"  knowledge_root: {reviewed['second_brain_vault']['path'] if reviewed['second_brain_vault']['enabled'] else '.'}",
                        "  planning_root: .",
                        *(["governance:", "  required: true", "  context_path: .development-platform/governance.json", f"  context_digest: {governance_record['provenance']['record_digest']}"] if governance_record is not None else []),
                        "repository_intelligence:",
                        "  enabled: false",
                        "  degraded_mode: startup-without-trusted-context",
                        "agents:",
                        "  claude: true",
                        "  codex: true",
                        "  opencode: true",
                        "gsd:",
                        "  enabled: false",
                        "session_brief:",
                        "  enabled: false",
                        "runtime_history:",
                        "  enabled: false",
                    ]
                ) + "\n",
                encoding="utf-8",
            )
        elif vault_selected:
            try:
                declaration_data = yaml.safe_load(declaration.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise RadixInitCLIError(f"cannot read project declaration: {exc}") from exc
            if not isinstance(declaration_data, dict) or not isinstance(declaration_data.get("project"), dict):
                raise RadixInitCLIError("project declaration must contain a project object")
            declaration_data = deepcopy(declaration_data)
            declaration_data["project"]["knowledge_root"] = reviewed["second_brain_vault"]["path"]
            declaration.write_text(yaml.safe_dump(declaration_data, sort_keys=False), encoding="utf-8")
        startup_validated = False
        if startup_config:
            if not any(selection["capability"] == "gsd" for selection in reviewed["selections"]):
                raise RadixInitCLIError("guided apply requires the gsd capability for governed startup")
            try:
                resolution = WorkspaceBoundRadix(project).resolve_startup(
                    session_id=f"radix-init-{reviewed['project_id']}",
                    agent=startup_config["agent"],
                    current_objective=startup_config["objective"],
                )
            except (OSError, WorkspaceDiscoveryError, ValueError) as exc:
                raise RadixInitCLIError(f"guided startup validation failed: {exc}") from exc
            if not resolution.ready or not resolution.execution_allowed:
                reasons = ", ".join(resolution.blocking_reasons) or "startup authority unresolved"
                raise RadixInitCLIError(f"guided startup validation failed: {reasons}")
            startup_validated = True
        if reviewed.get("planning", {}).get("create_gsd_architecture_draft"):
            if not startup_config or planning_root is None:
                raise RadixInitCLIError("GSD architecture draft requires guided startup configuration")
            generated = _create_gsd_architecture_draft(
                project=project,
                project_id=reviewed["project_id"],
                project_context=reviewed.get("project_context"),
                startup_config=startup_config,
                planning_root=planning_root,
            )
            generated_phase_paths = [
                Path(generated["phase_path"]),
                Path(generated["specification_path"]),
                Path(generated["preparation_path"]),
            ]

        quality_initializer = Path(__file__).resolve().parents[2] / "scripts" / "init-development-quality.sh"
        initializer_args = [
        str(quality_initializer),
        "--project", str(project),
        "--project-id", reviewed["project_id"],
    ]
        for selection in reviewed["selections"]:
            initializer_args.extend(["--capability", selection["capability"]])
            for profile in selection["profiles"]:
                initializer_args.extend(["--profile", f"{selection['capability']}={profile['id']}@{profile['version']}"])
        transport = (reviewed.get("review_transport") or {}).get("ocr", {})
        try:
            subprocess.run(initializer_args, check=True, cwd=str(Path(__file__).resolve().parents[2]), capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RadixInitCLIError(f"quality-layer initialization failed: {exc}") from exc
        # The shared initializer intentionally exposes only the direct provider
        # route.  Keep an explicitly approved optional route as configuration
        # data without making it executable or placing secret-manager commands
        # in project hooks.  The plan's review transport remains authoritative.
        if transport.get("transport") not in (None, "direct") and startup_config:
            # Guided startup remains deterministic: optional transport values
            # are retained in the manifest, while the generated hook does not
            # activate an external reviewer or secret-manager integration.
            quality_config = project / ".development-platform/quality-hooks.json"
            try:
                settings = json.loads(quality_config.read_text(encoding="utf-8"))
                settings["ai_review"] = False
                quality_config.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
            except (OSError, json.JSONDecodeError) as exc:
                raise RadixInitCLIError(f"review transport configuration failed: {exc}") from exc
        elif transport.get("transport") not in (None, "direct"):
            quality_config = project / ".development-platform/quality-hooks.json"
            try:
                settings = json.loads(quality_config.read_text(encoding="utf-8"))
                settings["transport"] = transport["transport"]
                settings["infisical_project_id"] = transport.get("infisical_project_id", "")
                settings["infisical_env"] = transport.get("infisical_env", "prod")
                settings["infisical_path"] = transport.get("infisical_path", "/omniroute")
                quality_config.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
                quality_yaml = project / ".development-platform/quality.yaml"
                if quality_yaml.exists():
                    quality_text = quality_yaml.read_text(encoding="utf-8")
                    quality_yaml.write_text(
                        re.sub(r"(?m)^(  transport: ).*$", rf"\g<1>{transport['transport']}", quality_text),
                        encoding="utf-8",
                    )
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                raise RadixInitCLIError(f"review transport configuration failed: {exc}") from exc
        launcher = project / "radix.sh"
        if "radix.sh" in reviewed["generated_artifacts"]:
            _install_project_launcher(launcher)
        if reviewed["second_brain_vault"]["enabled"]:
            _initialize_obsidian_vault(project, reviewed["second_brain_vault"]["path"])
    except Exception:
        for generated_path in generated_phase_paths:
            if generated_path.exists():
                generated_path.unlink()
        if snapshots:
            _restore_paths(snapshots)
            if task_authority_path is not None and task_snapshot is not None:
                _restore_path(task_authority_path, task_snapshot)
            if planning_root is not None and planning_root.exists() and not any(planning_root.iterdir()):
                planning_root.rmdir()
        raise
    return {
        "schema": "radix-guided-bootstrap-application.v1",
        "plan_path": reviewed["plan_path"],
        "manifest_path": str(manifest),
        "declaration_path": str(declaration),
        "launcher_path": str(project / "radix.sh") if "radix.sh" in reviewed["generated_artifacts"] else None,
        "vault_path": (
            str(_resolve_project_path(project, reviewed["second_brain_vault"]["path"]))
            if reviewed["second_brain_vault"]["enabled"] else None
        ),
        "declaration_created": declaration_created,
        "project_id": reviewed["project_id"],
        "approval_required": False,
        "approval_verified": approval_verified,
        "activated": False,
        "quality_initialized": True,
        "startup_validated": startup_validated,
        "gsd_architecture_draft": (
            {
                "phase_path": str(generated_phase_paths[0]),
                "specification_path": str(generated_phase_paths[1]),
                "preparation_path": str(generated_phase_paths[2]),
            }
            if generated_phase_paths else None
        ),
    }


def _install_project_launcher(path: Path) -> None:
    """Install a project-local Radix entrypoint without replacing owner files."""

    core_radix = Path(__file__).resolve().parents[2] / "radix"
    body = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"\n'
        f"CORE_RADIX={shlex.quote(str(core_radix))}\n"
        'if [[ ! -x "$CORE_RADIX" ]]; then\n'
        '  CORE_RADIX="${RADIX_BIN:-radix}"\n'
        'fi\n'
        'exec "$CORE_RADIX" --project "$PROJECT_ROOT" "$@"\n'
    )
    try:
        with path.open("x", encoding="utf-8") as launcher:
            launcher.write(body)
        path.chmod(0o755)
    except FileExistsError:
        # Existing project launchers belong to the project owner.
        return


def _initialize_obsidian_vault(project: Path, relative_path: str) -> None:
    """Create a small Obsidian-compatible second-brain scaffold, preserving owner notes."""

    root = _resolve_project_path(project, relative_path)
    notes = {
        "Home.md": "---\ntitle: Second Brain\ntags:\n  - home\n  - second-brain\n---\n\n# Second Brain\n\nCapture ideas in [[00-Inbox]]. Organize durable knowledge in [[Projects/Projects]] and [[Reference/Reference]].\n",
        "00-Inbox.md": "---\ntitle: Inbox\ntags:\n  - inbox\n---\n\n# Inbox\n\nCapture first; sort into [[Projects/Projects]] or [[Reference/Reference]] when useful.\n",
        "Projects/Projects.md": "---\ntitle: Projects\ntags:\n  - projects\n---\n\n# Projects\n\nProject notes live here. Link related decisions and references with Obsidian wikilinks.\n",
        "Reference/Reference.md": "---\ntitle: Reference\ntags:\n  - reference\n---\n\n# Reference\n\nDurable facts, sources, and reusable notes live here.\n",
    }
    if root.exists() and not root.is_dir():
        raise RadixInitCLIError(f"Obsidian vault path exists and is not a directory: {root}")
    for relative_note in notes:
        target = root / relative_note
        if target.exists() and not target.is_file():
            raise RadixInitCLIError(f"Obsidian note path exists and is not a file: {target}")
    created: list[Path] = []
    created_directories: list[Path] = []
    try:
        directories = [root, root / "Projects", root / "Reference"]
        for directory in directories:
            if not directory.exists():
                directory.mkdir()
                created_directories.append(directory)
        for relative_note, content in notes.items():
            target = root / relative_note
            try:
                with target.open("x", encoding="utf-8") as note:
                    note.write(content)
                created.append(target)
            except FileExistsError:
                continue
    except OSError:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def _snapshot_path(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def _snapshot_paths(paths: Sequence[Path]) -> dict[Path, tuple[bool, bytes | None]]:
    return {path: _snapshot_path(path) for path in paths}


def _restore_path(path: Path, snapshot: tuple[bool, bytes | None]) -> None:
    existed, content = snapshot
    if existed and content is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    elif path.exists():
        path.unlink()


def _restore_paths(snapshots: dict[Path, tuple[bool, bytes | None]]) -> None:
    for path, snapshot in snapshots.items():
        _restore_path(path, snapshot)


def _resolve_project_path(project: Path, value: str) -> Path:
    path = Path(value).expanduser()
    resolved = (path if path.is_absolute() else project / path).resolve()
    try:
        resolved.relative_to(project)
    except ValueError as exc:
        raise RadixInitCLIError("guided startup paths must remain inside the project root") from exc
    return resolved


def _apply_startup_configuration(
    declaration: dict[str, Any],
    *,
    project_id: str,
    startup_config: dict[str, str],
) -> None:
    if declaration.get("schema") != "development-platform.v1":
        raise RadixInitCLIError("guided apply requires development-platform.v1 declaration")
    project = declaration.setdefault("project", {})
    project["id"] = project_id
    project.setdefault("root", ".")
    project.setdefault("knowledge_root", ".")
    project["planning_root"] = ".development-platform/gsd-phases"
    declaration["capabilities_manifest"] = ".development-platform/capabilities.yaml"
    agents = declaration.setdefault("agents", {})
    agents.setdefault("claude", True)
    agents.setdefault("codex", True)
    agents.setdefault("opencode", True)
    agents[startup_config["agent"]] = True
    declaration["gsd"] = {
        "enabled": True,
        "session_governance": "gsd-session-governance.v1",
        "planning_root": ".development-platform/gsd-phases",
        "task_authority": startup_config["task_authority"],
    }
