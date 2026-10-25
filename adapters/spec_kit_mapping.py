"""Dependency-free Spec Kit to Core stage mapping.

This module is deliberately only a mapping boundary. It does not invoke Spec
Kit, read provider files, approve gates, verify implementation, or create
acceptance state.
"""

from __future__ import annotations

from typing import Final, TypedDict


class SpecKitMappingError(ValueError):
    """Raised when a provider operation has no safe Core translation."""


class StageMapping(TypedDict):
    stage: str
    artifact_kind: str
    authority: str


_MAPPINGS: Final[dict[str, StageMapping]] = {
    "intake": {"stage": "INTENT", "artifact_kind": "intent", "authority": "report_only"},
    "/specify": {"stage": "SPECIFICATION", "artifact_kind": "specification", "authority": "core_gate_required"},
    "/speckit.specify": {"stage": "SPECIFICATION", "artifact_kind": "specification", "authority": "core_gate_required"},
    "assessment": {"stage": "ASSESSMENT", "artifact_kind": "assessment", "authority": "core_gate_required"},
    "/plan": {"stage": "PLAN", "artifact_kind": "plan", "authority": "core_gate_required"},
    "/speckit.plan": {"stage": "PLAN", "artifact_kind": "plan", "authority": "core_gate_required"},
    "/tasks": {"stage": "TASKS", "artifact_kind": "task_list", "authority": "core_gate_required"},
    "/speckit.tasks": {"stage": "TASKS", "artifact_kind": "task_list", "authority": "core_gate_required"},
    "/implement": {"stage": "IMPLEMENTATION", "artifact_kind": "implementation", "authority": "report_only"},
    "/speckit.implement": {"stage": "IMPLEMENTATION", "artifact_kind": "implementation", "authority": "report_only"},
    "independent_verification": {"stage": "VERIFICATION", "artifact_kind": "verification", "authority": "independent_verifier_only"},
    "/converge": {"stage": "CONVERGENCE", "artifact_kind": "convergence", "authority": "assessment_only"},
    "/speckit.converge": {"stage": "CONVERGENCE", "artifact_kind": "convergence", "authority": "assessment_only"},
    "acceptance": {"stage": "ACCEPTANCE", "artifact_kind": "acceptance", "authority": "core_acceptance_authority_only"},
}


def map_operation(operation: str) -> StageMapping:
    """Return a copy of the safe Core mapping for one provider operation."""

    key = operation.strip().lower()
    try:
        return dict(_MAPPINGS[key])
    except KeyError as exc:
        raise SpecKitMappingError(f"unsupported or unmapped Spec Kit operation: {operation!r}") from exc


def validate_provider_claim(operation: str, claimed_stage: str, claimed_kind: str) -> StageMapping:
    """Reject provider claims that cross Core verification or acceptance boundaries."""

    mapping = map_operation(operation)
    if mapping["stage"] != claimed_stage or mapping["artifact_kind"] != claimed_kind:
        raise SpecKitMappingError(
            f"provider claim for {operation!r} does not match Core mapping "
            f"({mapping['stage']}, {mapping['artifact_kind']})"
        )
    return mapping
