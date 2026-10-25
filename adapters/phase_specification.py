"""Validation, identity, and compatibility helpers for phase-specification.v1."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "phase-specification.v1.schema.json"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class PhaseSpecificationError(ValueError):
    """Raised when a phase specification cannot be trusted as authoritative."""


@dataclass(frozen=True)
class SpecificationResolution:
    specification_id: str
    phase_id: str
    version: str
    specification_hash: str


@dataclass(frozen=True)
class SkillResolution:
    skill_id: str
    skill_version: str
    skill_hash: str


ONE_SHOT_POLICY_REF = "GSD-MASTER-GLOBAL-ONE-SHOT-ORCHESTRATION-POLICY-v1.1"


class SpecificationRegistry:
    """Authority registry for immutable specification identities."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: dict[tuple[str, str], str] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PhaseSpecificationError("specification registry must contain an object")
        records: dict[tuple[str, str], str] = {}
        for key, value in payload.items():
            parts = str(key).split("\n", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise PhaseSpecificationError("specification registry contains an invalid identity key")
            records[(parts[0], parts[1])] = str(value)
        self._records = records

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {f"{specification_id}\n{version}": digest for (specification_id, version), digest in self._records.items()}
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def register(self, resolution: SpecificationResolution) -> None:
        key = (resolution.specification_id, resolution.version)
        existing = self._records.get(key)
        if existing is not None and existing != resolution.specification_hash:
            raise PhaseSpecificationError(
                f"specification identity already registered with a different hash: {key}"
            )
        self._records[key] = resolution.specification_hash
        self._persist()

    def resolve(self, specification_id: str, version: str) -> str:
        try:
            return self._records[(specification_id, version)]
        except KeyError as exc:
            raise PhaseSpecificationError(f"unknown specification identity: {(specification_id, version)}") from exc


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def canonical_payload(specification: Mapping[str, Any]) -> dict[str, Any]:
    """Return the content covered by specification_hash."""
    payload = json.loads(json.dumps(specification))
    phase = payload.get("phase")
    if isinstance(phase, dict):
        phase.pop("specification_hash", None)
    return payload


def calculate_specification_hash(specification: Mapping[str, Any]) -> str:
    encoded = json.dumps(canonical_payload(specification), sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def resolve_skill_identity(skill_path: str | Path, *, skill_id: str = "gsd:master") -> SkillResolution:
    """Resolve the immutable identity of the skill that executes a run."""
    path = Path(skill_path)
    content = path.read_bytes()
    version = None
    for line in content.decode("utf-8").splitlines():
        if line.startswith("version:"):
            version = line.split(":", 1)[1].strip()
            break
    if not version:
        raise PhaseSpecificationError("skill version is missing from SKILL.md")
    return SkillResolution(skill_id, version, "sha256:" + hashlib.sha256(content).hexdigest())


def validate_phase_specification(specification: Mapping[str, Any], *, verify_hash: bool = True) -> SpecificationResolution:
    if not isinstance(specification, Mapping):
        raise PhaseSpecificationError("specification must be an object")
    errors = sorted(Draft202012Validator(_schema(), format_checker=FormatChecker()).iter_errors(specification), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "root"
        raise PhaseSpecificationError(f"invalid phase-specification.v1 at {location}: {errors[0].message}")
    phase = specification["phase"]
    requirements = specification["requirements"]
    requirement_ids = [item["requirement_id"] for item in requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise PhaseSpecificationError("duplicate requirement_id")
    criterion_ids = [criterion["criterion_id"] for item in requirements for criterion in item["acceptance_criteria"]]
    if len(criterion_ids) != len(set(criterion_ids)):
        raise PhaseSpecificationError("duplicate criterion_id")
    task_ids = [task["task_id"] for task in specification["implementation"]["tasks"]]
    task_set = set(task_ids)
    if len(task_ids) != len(task_set):
        raise PhaseSpecificationError("duplicate task_id")
    requirement_set = set(requirement_ids)
    for requirement in requirements:
        unknown = set(requirement["dependencies"]) - requirement_set
        if unknown:
            raise PhaseSpecificationError(
                f"requirement {requirement['requirement_id']} references unknown dependencies: {sorted(unknown)}"
            )
        if requirement["mandatory"] and not any(item["required"] for item in requirement["evidence_contract"]):
            raise PhaseSpecificationError(
                f"mandatory requirement {requirement['requirement_id']} has no required evidence contract"
            )
    for task in specification["implementation"]["tasks"]:
        unknown = set(task["requirement_refs"]) - requirement_set
        if unknown:
            raise PhaseSpecificationError(f"task {task['task_id']} references unknown requirements: {sorted(unknown)}")
        unknown = set(task["depends_on"]) - task_set
        if unknown:
            raise PhaseSpecificationError(f"task {task['task_id']} references unknown dependencies: {sorted(unknown)}")
    _assert_acyclic(specification["implementation"]["tasks"])
    covered_requirements = {
        requirement_ref
        for task in specification["implementation"]["tasks"]
        for requirement_ref in task["requirement_refs"]
    }
    uncovered = {item["requirement_id"] for item in requirements if item["mandatory"]} - covered_requirements
    if uncovered:
        raise PhaseSpecificationError(f"mandatory requirements have no implementation task: {sorted(uncovered)}")
    if phase["workflow"]["workflow_id"] is not None:
        raise PhaseSpecificationError("workflow_id is derived and must be null in the authoritative specification")
    calculated = calculate_specification_hash(specification)
    if verify_hash and phase["specification_hash"] != calculated:
        raise PhaseSpecificationError("specification_hash does not match canonical specification content")
    return SpecificationResolution(phase["specification_id"], phase["phase_id"], phase["version"], phase["specification_hash"])


def validate_phase_one_shot_specification(
    specification: Mapping[str, Any], *, verify_hash: bool = True
) -> SpecificationResolution:
    """Validate a new/revisioned phase against the active one-shot policy."""

    resolution = validate_phase_specification(specification, verify_hash=verify_hash)
    phase = specification["phase"]
    refs = phase["provenance"]["source_refs"]
    if ONE_SHOT_POLICY_REF not in refs:
        raise PhaseSpecificationError(
            "phase does not reference the active one-shot orchestration policy"
        )
    strategy = specification["implementation"]["execution_strategy"].lower()
    required_terms = ("one", "phase", "dependency", "review")
    if not all(term in strategy for term in required_terms):
        raise PhaseSpecificationError(
            "phase execution strategy does not establish phase-level one-shot execution"
        )
    if not specification["independent_review"]["required"]:
        raise PhaseSpecificationError(
            "one-shot phases must derive independent review from phase risk"
        )
    conditions = " ".join(specification["acceptance"]["required_conditions"]).lower()
    if "separate" not in conditions or "acceptance" not in conditions:
        raise PhaseSpecificationError(
            "one-shot phase must preserve a separate acceptance decision"
        )
    return resolution


def _assert_acyclic(tasks: list[Mapping[str, Any]]) -> None:
    edges = {task["task_id"]: set(task["depends_on"]) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise PhaseSpecificationError("implementation task dependencies contain a cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in edges[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)


def resolve_acceptance_binding(specification: Mapping[str, Any]) -> dict[str, str]:
    resolution = validate_phase_specification(specification)
    return {"phase_id": resolution.phase_id, "specification_id": resolution.specification_id, "specification_version": resolution.version, "specification_hash": resolution.specification_hash}


def validate_execution_plan(
    specification: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> SpecificationResolution:
    """Validate a derived execution plan against the authoritative specification.

    The plan may choose scheduling metadata, but it cannot change task identity,
    intent, dependency edges, requirement coverage, or expected artifacts.
    """
    resolution = validate_phase_specification(specification)
    if not isinstance(plan, Mapping):
        raise PhaseSpecificationError("execution plan must be an object")

    expected_identity = {
        "phase_id": resolution.phase_id,
        "specification_id": resolution.specification_id,
        "specification_version": resolution.version,
        "specification_hash": resolution.specification_hash,
    }
    for field, expected in expected_identity.items():
        if plan.get(field) != expected:
            raise PhaseSpecificationError(
                f"execution plan {field} does not match authoritative specification"
            )

    for field in ("skill_id", "skill_version", "skill_hash"):
        if not isinstance(plan.get(field), str) or not plan[field].strip():
            raise PhaseSpecificationError(f"execution plan {field} is required")

    tasks = plan.get("tasks")
    if tasks is None and isinstance(plan.get("dag"), Mapping):
        tasks = plan["dag"].get("tasks")
    if not isinstance(tasks, list):
        raise PhaseSpecificationError("execution plan must contain tasks")

    authoritative = {task["task_id"]: task for task in specification["implementation"]["tasks"]}
    planned = {}
    for task in tasks:
        if not isinstance(task, Mapping) or not isinstance(task.get("task_id"), str):
            raise PhaseSpecificationError("execution plan contains an invalid task")
        task_id = task["task_id"]
        if task_id in planned:
            raise PhaseSpecificationError(f"execution plan contains duplicate task_id: {task_id}")
        planned[task_id] = task

    if set(planned) != set(authoritative):
        missing = sorted(set(authoritative) - set(planned))
        unexpected = sorted(set(planned) - set(authoritative))
        raise PhaseSpecificationError(
            f"execution plan task set diverges from specification: missing={missing}, unexpected={unexpected}"
        )

    governed_fields = ("statement", "depends_on", "requirement_refs", "expected_artifacts")
    for task_id, expected in authoritative.items():
        actual = planned[task_id]
        for field in governed_fields:
            if actual.get(field) != expected[field]:
                raise PhaseSpecificationError(
                    f"execution plan task {task_id} {field} diverges from specification"
                )
    return resolution


def inspect_historical_phase(path: str | Path) -> dict[str, Any]:
    """Report recoverable Markdown facts without fabricating a specification."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = [line[3:].strip() for line in lines if line.startswith("## ")]
    version = next((line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("version:")), None)
    phase_id = next((line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("phase:") and ":" in line), None)
    criteria = [line.strip() for line in lines if line.strip().startswith("- [")]
    return {"path": str(path), "phase_id": phase_id, "version": version, "headings": headings, "acceptance_criteria": criteria, "migration_gap": "semantic fields not recoverable without interpretation"}
