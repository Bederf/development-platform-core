"""Resolve DPC GSD phase artifacts without creating a second authority."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .phase_authorization import FileAuthorizationStore, PhaseAuthorizationError
from .phase_specification import SpecificationResolution, validate_phase_specification


class GsdPhaseResolutionError(ValueError):
    """Raised when a phase cannot be resolved unambiguously and safely."""


@dataclass(frozen=True)
class GsdPhaseResolution:
    """The selected human artifact and its authoritative semantic sidecar."""

    phase_id: str
    specification_id: str
    specification_version: str
    specification_hash: str
    markdown_path: Path
    specification_path: Path


_PHASE_NUMBER = re.compile(r"^(?:P)?([0-9]+)$", re.IGNORECASE)
_DPC_PROJECT_ID = "development-platform-core"
_DPC_ROOT = Path(__file__).resolve().parents[1]


def _phase_binding_id(phase_id: str) -> str:
    """Derive the subject-bound binding identity without a phase-specific constant."""

    if not re.fullmatch(r"P[0-9]{3}", phase_id):
        raise GsdPhaseResolutionError(f"invalid resolved phase identity: {phase_id}")
    return f"phase-{phase_id[1:]}-specification-binding"


def _project_phase_binding_id(project_id: str, phase_id: str) -> str:
    """Derive a namespace-safe project binding identity."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", project_id):
        raise GsdPhaseResolutionError(f"invalid project identity: {project_id!r}")
    if not re.fullmatch(r"P[0-9]{3}", phase_id):
        raise GsdPhaseResolutionError(f"invalid resolved phase identity: {phase_id}")
    return f"project-{project_id}-phase-{phase_id[1:]}-specification-binding"


def _phase_number(argument: str) -> str:
    match = _PHASE_NUMBER.fullmatch(argument.strip())
    if not match:
        raise GsdPhaseResolutionError(f"invalid phase argument: {argument!r}")
    return match.group(1).zfill(3)


def _regular_file(path: Path, description: str) -> None:
    if path.is_symlink():
        raise GsdPhaseResolutionError(f"{description} must not be a symlink: {path}")
    if not path.is_file():
        raise GsdPhaseResolutionError(f"{description} is missing or not a regular file: {path}")


def _candidate_markdown(
    root: Path,
    phase_number: str,
    *,
    allow_project_prefix: bool = False,
) -> Path:
    exact = root / f"Phase-{phase_number}.md"
    descriptive = sorted(root.glob(f"Phase-{phase_number}-*.md"))
    candidates = ([exact] if exact.exists() else []) + descriptive
    if allow_project_prefix:
        prefixed_exact = root / f"Phase-P{phase_number}.md"
        prefixed_descriptive = sorted(root.glob(f"Phase-P{phase_number}-*.md"))
        candidates += ([prefixed_exact] if prefixed_exact.exists() else [])
        candidates += prefixed_descriptive
        # Project workspaces may retain a draft Markdown artifact beside the
        # canonical phase. Only a Markdown/sidecar pair is a resolvable phase;
        # multiple complete pairs remain ambiguous and fail closed below.
        candidates = [
            path
            for path in candidates
            if not path.is_symlink()
            and path.with_name(path.name.removesuffix(".md") + ".specification.json").is_file()
        ]
    if len(candidates) != 1:
        if not candidates:
            raise GsdPhaseResolutionError(
                f"no phase artifact found for Phase-{phase_number} under {root}"
            )
        raise GsdPhaseResolutionError(
            f"ambiguous phase artifacts for Phase-{phase_number}: "
            + ", ".join(str(path) for path in candidates)
        )
    selected = candidates[0]
    _regular_file(selected, "phase artifact")
    return selected


def _resolve_dpc_phase(planning_root: str | Path, argument: str) -> GsdPhaseResolution:
    """Locate one phase artifact under an already-authorized planning root.

    The descriptive Markdown name is only a locator. The adjacent
    ``phase-specification.v1`` sidecar remains the sole semantic authority.
    No alias, copy, or alternate specification is created or accepted.
    """

    root = Path(planning_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise GsdPhaseResolutionError(f"planning root is unavailable or unsafe: {root}")
    number = _phase_number(argument)
    markdown_path = _candidate_markdown(root, number)
    specification_path = markdown_path.with_name(markdown_path.name.removesuffix(".md") + ".specification.json")
    _regular_file(specification_path, "phase specification")
    try:
        specification: Mapping[str, object] = json.loads(
            specification_path.read_text(encoding="utf-8")
        )
        resolution: SpecificationResolution = validate_phase_specification(specification)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise GsdPhaseResolutionError(
            f"invalid phase specification for {markdown_path}: {exc}"
        ) from exc

    expected_phase_id = f"P{number}"
    if resolution.phase_id != expected_phase_id:
        raise GsdPhaseResolutionError(
            f"phase identity mismatch: expected {expected_phase_id}, got {resolution.phase_id}"
        )

    markdown = markdown_path.read_text(encoding="utf-8")
    if not re.search(rf"^phase_id:\s*{re.escape(expected_phase_id)}\s*$", markdown, re.MULTILINE):
        raise GsdPhaseResolutionError(
            f"Markdown phase identity does not bind to {expected_phase_id}: {markdown_path}"
        )

    return GsdPhaseResolution(
        phase_id=resolution.phase_id,
        specification_id=resolution.specification_id,
        specification_version=resolution.version,
        specification_hash=resolution.specification_hash,
        markdown_path=markdown_path,
        specification_path=specification_path,
    )


def _resolve_project_phase(planning_root: str | Path, argument: str) -> GsdPhaseResolution:
    """Resolve a project phase using the project's P-prefixed naming form."""

    root = Path(planning_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise GsdPhaseResolutionError(f"project planning root is unavailable or unsafe: {root}")
    number = _phase_number(argument)
    markdown_path = _candidate_markdown(root, number, allow_project_prefix=True)
    specification_path = markdown_path.with_name(
        markdown_path.name.removesuffix(".md") + ".specification.json"
    )
    _regular_file(specification_path, "project phase specification")
    try:
        specification: Mapping[str, object] = json.loads(
            specification_path.read_text(encoding="utf-8")
        )
        resolution: SpecificationResolution = validate_phase_specification(specification)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise GsdPhaseResolutionError(
            f"invalid project phase specification for {markdown_path}: {exc}"
        ) from exc
    expected_phase_id = f"P{number}"
    if resolution.phase_id != expected_phase_id:
        raise GsdPhaseResolutionError(
            f"project phase identity mismatch: expected {expected_phase_id}, got {resolution.phase_id}"
        )
    markdown = markdown_path.read_text(encoding="utf-8")
    if not re.search(
        rf"^(?:phase_id|phase):\s*{re.escape(expected_phase_id)}\s*$",
        markdown,
        re.MULTILINE,
    ):
        raise GsdPhaseResolutionError(
            f"project Markdown phase identity does not bind to {expected_phase_id}: {markdown_path}"
        )
    return GsdPhaseResolution(
        phase_id=resolution.phase_id,
        specification_id=resolution.specification_id,
        specification_version=resolution.version,
        specification_hash=resolution.specification_hash,
        markdown_path=markdown_path,
        specification_path=specification_path,
    )


def resolve_authoritative_dpc_phase(
    project_id: str,
    repository_root: str | Path,
    planning_root: str | Path,
    argument: str,
) -> GsdPhaseResolution:
    return _resolve_authoritative_dpc_phase(
        project_id,
        repository_root,
        planning_root,
        argument,
        core_root=_DPC_ROOT,
        authority_store=FileAuthorizationStore(),
    )


def resolve_authoritative_project_phase(
    project_id: str,
    repository_root: str | Path,
    planning_root: str | Path,
    argument: str,
) -> GsdPhaseResolution:
    """Resolve a consumer project's local phase through DPC authority.

    The phase artifact and sidecar are read from the consuming repository. The
    Core authority index supplies only the exact project/subject binding.
    """

    return _resolve_authoritative_project_phase(
        project_id,
        repository_root,
        planning_root,
        argument,
        core_root=_DPC_ROOT,
        authority_store=FileAuthorizationStore(),
    )


def _resolve_authoritative_project_phase(
    project_id: str,
    repository_root: str | Path,
    planning_root: str | Path,
    argument: str,
    *,
    core_root: Path,
    authority_store: FileAuthorizationStore,
) -> GsdPhaseResolution:
    if project_id == _DPC_PROJECT_ID:
        raise GsdPhaseResolutionError(
            "DPC Core phases must use resolve_authoritative_dpc_phase"
        )
    root = Path(repository_root).expanduser().resolve(strict=True)
    trusted_root = core_root.expanduser().resolve(strict=True)
    if root == trusted_root:
        raise GsdPhaseResolutionError("project phase root must not be the DPC Core root")
    declared_planning_root = Path(planning_root).expanduser().resolve(strict=True)
    if Path(repository_root).is_symlink() or Path(planning_root).is_symlink():
        raise GsdPhaseResolutionError("project repository and planning roots must not be symlinks")
    try:
        declared_planning_root.relative_to(root)
    except ValueError as exc:
        raise GsdPhaseResolutionError(
            "project planning root must be contained by the canonical repository root"
        ) from exc
    selected = _resolve_project_phase(declared_planning_root, argument)
    subject = {
        "project_id": project_id,
        "repository_root": str(root),
        "planning_root": str(declared_planning_root),
        "phase_id": selected.phase_id,
        "specification_id": selected.specification_id,
        "specification_version": selected.specification_version,
        "specification_hash": selected.specification_hash,
    }
    try:
        authority_store.resolve_project_phase_specification_binding(
            _project_phase_binding_id(project_id, selected.phase_id),
            subject=subject,
        )
    except PhaseAuthorizationError as exc:
        raise GsdPhaseResolutionError(str(exc)) from exc
    return selected


def _resolve_authoritative_dpc_phase(
    project_id: str,
    repository_root: str | Path,
    planning_root: str | Path,
    argument: str,
    *,
    core_root: Path,
    authority_store: FileAuthorizationStore,
) -> GsdPhaseResolution:
    """Resolve a phase through the fixed DPC authority root.

    The declaration-derived values are checked against the trusted Core runtime
    root before any phase artifact is accepted. The selected descriptive
    artifact is then bound through the existing Core authorization mechanism.
    """

    if project_id != _DPC_PROJECT_ID:
        raise GsdPhaseResolutionError("phase authority requires the canonical DPC project")
    root = Path(repository_root).expanduser().resolve(strict=True)
    trusted_root = core_root.expanduser().resolve(strict=True)
    if root != trusted_root:
        raise GsdPhaseResolutionError("phase authority requires the canonical DPC repository root")
    declared_planning_root = Path(planning_root).expanduser().resolve(strict=True)
    canonical_planning_root = trusted_root / "00-GSD-Phases"
    if declared_planning_root != canonical_planning_root:
        raise GsdPhaseResolutionError("phase authority planning root is not the canonical DPC root")
    if Path(planning_root).is_symlink() or not canonical_planning_root.is_dir():
        raise GsdPhaseResolutionError(
            f"DPC planning root is unavailable or unsafe: {canonical_planning_root}"
        )

    selected = _resolve_dpc_phase(canonical_planning_root, argument)
    try:
        authority_store.resolve_phase_specification_binding(
            _phase_binding_id(selected.phase_id),
            subject={
                "phase_id": selected.phase_id,
                "specification_id": selected.specification_id,
                "specification_version": selected.specification_version,
                "specification_hash": selected.specification_hash,
            },
        )
    except PhaseAuthorizationError as exc:
        raise GsdPhaseResolutionError(str(exc)) from exc
    matches: list[SpecificationResolution] = []
    for path in sorted(canonical_planning_root.glob("*.specification.json")):
        _regular_file(path, "canonical phase specification")
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            resolution = validate_phase_specification(candidate)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise GsdPhaseResolutionError(
                f"invalid canonical phase specification {path}: {exc}"
            ) from exc
        if (
            resolution.specification_id == selected.specification_id
            and resolution.version == selected.specification_version
        ):
            matches.append(resolution)

    if len(matches) != 1:
        raise GsdPhaseResolutionError(
            "DPC specification identity is not uniquely bound in the canonical root"
        )
    approved = matches[0]
    if approved.specification_hash != selected.specification_hash:
        raise GsdPhaseResolutionError(
            "phase specification digest does not match the independently resolved "
            "DPC authority record"
        )
    return selected
