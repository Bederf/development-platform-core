"""Prepare a governed phase for one-shot execution without granting authority.

Phase creation is mechanical preparation.  It validates the authoritative
sidecar and Markdown locator, derives the dependency graph and risk review
route, and prepares one phase-level Founder decision for the existing session
mechanism.  It never issues a binding, confirms a decision, or authorizes work.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Any

from .phase_specification import SpecificationResolution, validate_phase_one_shot_specification


class PhaseCreationError(ValueError):
    """Raised when a phase cannot be prepared safely."""


@dataclass(frozen=True)
class PhaseCreationPackage:
    """Derived preparation data; none of it is authority evidence."""

    resolution: SpecificationResolution
    specification_path: Path
    markdown_path: Path
    task_order: tuple[str, ...]
    task_graph: tuple[Mapping[str, Any], ...]
    checks: tuple[str, ...]
    evidence_path: str
    review_required: bool
    review_provider_ref: str
    decision_template: Mapping[str, Any]
    prepared_record: Mapping[str, Any]


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise PhaseCreationError(f"refusing to overwrite phase preparation: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _ordered_tasks(tasks: list[Mapping[str, Any]]) -> tuple[str, ...]:
    by_id = {str(task["task_id"]): task for task in tasks}
    if len(by_id) != len(tasks):
        raise PhaseCreationError("phase task graph contains duplicate task identities")
    remaining = {task_id: set(task["depends_on"]) for task_id, task in by_id.items()}
    unknown = sorted({dependency for dependencies in remaining.values() for dependency in dependencies} - set(by_id))
    if unknown:
        raise PhaseCreationError(f"phase task graph references unknown tasks: {unknown}")
    ordered: list[str] = []
    while remaining:
        ready = sorted(task_id for task_id, dependencies in remaining.items() if not dependencies)
        if not ready:
            raise PhaseCreationError("phase task graph contains a cycle")
        ordered.extend(ready)
        for task_id in ready:
            del remaining[task_id]
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return tuple(ordered)


def prepare_phase_creation(
    *,
    specification_path: str | Path,
    markdown_path: str | Path,
    evidence_path: str | Path,
    preparation_path: str | Path | None = None,
    review_provider_ref: str | None = None,
) -> PhaseCreationPackage:
    """Prepare one consolidated phase decision from a validated phase pair."""

    spec_path = Path(specification_path)
    markdown = Path(markdown_path)
    if spec_path.is_symlink() or not spec_path.is_file():
        raise PhaseCreationError("phase specification is unavailable or unsafe")
    if markdown.is_symlink() or not markdown.is_file():
        raise PhaseCreationError("matching Markdown phase artifact is unavailable or unsafe")
    try:
        specification = json.loads(spec_path.read_text(encoding="utf-8"))
        resolution = validate_phase_one_shot_specification(specification)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PhaseCreationError("phase does not satisfy the active one-shot policy") from exc
    markdown_text = markdown.read_text(encoding="utf-8")
    if f"phase_id: {resolution.phase_id}" not in markdown_text and f"phase: {resolution.phase_id}" not in markdown_text:
        raise PhaseCreationError("Markdown artifact does not bind to the sidecar phase identity")

    implementation = specification["implementation"]
    tasks = [dict(task) for task in implementation["tasks"]]
    order = _ordered_tasks(tasks)
    independent_review = specification["independent_review"]
    review_required = independent_review["required"] is True
    provider = review_provider_ref or str(independent_review["authority"])
    if review_required and not provider.strip():
        raise PhaseCreationError("risk-derived review requires a provider reference")
    exclusions = list(specification["scope"]["non_goals"])
    decision_template = {
        "decision_id": f"{resolution.phase_id.lower()}-phase-execution",
        "phase_id": resolution.phase_id,
        "specification_ref": resolution.specification_id,
        "specification_hash": resolution.specification_hash,
        "action": "authorize-phase-execution",
        "exclusions": exclusions,
        "independent_review": {"required": review_required, "provider_ref": provider},
    }
    prepared_record: dict[str, Any] = {
        "schema": "gsd-phase-creation-preparation.v1",
        "authority_granted": False,
        "confirmation_required": True,
        "phase": {
            "phase_id": resolution.phase_id,
            "specification_id": resolution.specification_id,
            "specification_version": resolution.version,
            "specification_hash": resolution.specification_hash,
        },
        "specification_path": str(spec_path),
        "markdown_path": str(markdown),
        "execution": {
            "task_order": list(order),
            "task_graph": tasks,
            "required_checks": list(specification["verification"]["required_checks"]),
            "evidence_path": str(evidence_path),
        },
        "review_policy": {
            "required": review_required,
            "provider_ref": provider,
            "source": "validated phase risk policy",
        },
        "decision_template": decision_template,
    }
    if preparation_path is not None:
        _write_new(Path(preparation_path), prepared_record)
    return PhaseCreationPackage(
        resolution=resolution,
        specification_path=spec_path,
        markdown_path=markdown,
        task_order=order,
        task_graph=tuple(tasks),
        checks=tuple(specification["verification"]["required_checks"]),
        evidence_path=str(evidence_path),
        review_required=review_required,
        review_provider_ref=provider,
        decision_template=decision_template,
        prepared_record=prepared_record,
    )
