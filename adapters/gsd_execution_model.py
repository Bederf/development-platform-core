"""Fail-closed reference primitives for the governed GSD execution model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .phase_specification import (
    PhaseSpecificationError,
    resolve_skill_identity,
    validate_execution_plan,
)


class GsdExecutionModelError(ValueError):
    """Raised when a graph or transition cannot be safely represented."""


def authorize_phase_execution(
    specification: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    skill_path: str,
) -> dict[str, Any]:
    """Return an execution authorization only for a bound spec, plan, and skill."""
    try:
        resolution = validate_execution_plan(specification, plan)
        skill = resolve_skill_identity(skill_path)
    except PhaseSpecificationError as exc:
        raise GsdExecutionModelError(f"phase execution authorization denied: {exc}") from exc
    if plan.get("skill_id") != skill.skill_id or plan.get("skill_version") != skill.skill_version or plan.get("skill_hash") != skill.skill_hash:
        raise GsdExecutionModelError("phase execution authorization denied: skill identity mismatch")
    return {
        "decision": "AUTHORIZED",
        "phase_id": resolution.phase_id,
        "specification_id": resolution.specification_id,
        "specification_version": resolution.version,
        "specification_hash": resolution.specification_hash,
        "skill_id": skill.skill_id,
        "skill_version": skill.skill_version,
        "skill_hash": skill.skill_hash,
    }


@dataclass(frozen=True)
class TransitionDecision:
    decision: str
    reason_codes: tuple[str, ...]
    evidence: tuple[str, ...]


def select_profile(factors: Mapping[str, str]) -> str:
    """Select a traversal profile from bounded low/medium/high factors."""
    if not factors:
        raise GsdExecutionModelError("profile factors are required")
    if any(level not in {"low", "medium", "high"} for level in factors.values()):
        raise GsdExecutionModelError("profile factors must be low, medium, or high")
    score = sum({"low": 0, "medium": 1, "high": 2}[level] for level in factors.values())
    return "small" if score <= 2 else "medium" if score <= 7 else "large"


def evaluate_transition(graph: Mapping[str, Any], request: Mapping[str, Any]) -> TransitionDecision:
    """Admit a lifecycle transition only when graph, readiness, authority, and evidence agree."""
    if graph.get("entity_type") != "graph_definition":
        raise GsdExecutionModelError("graph must be a graph_definition")
    if request.get("entity_type") != "transition_request":
        raise GsdExecutionModelError("request must be a transition_request")

    current = request.get("current_state")
    requested = request.get("requested_state")
    transition = next(
        (item for item in graph["lifecycle_graph"]["transitions"] if item["from"] == current and item["to"] == requested),
        None,
    )
    reasons: list[str] = []
    if transition is None:
        reasons.append("transition_not_defined")
    elif transition["requires_authorization"] and request.get("authorization") is not True:
        reasons.append("authorization_required")
    if not request.get("ready_nodes"):
        reasons.append("dag_readiness_missing")
    required = set(transition["required_evidence"]) if transition else set()
    supplied = set(request.get("evidence", ()))
    if not required.issubset(supplied):
        reasons.append("required_evidence_missing")
    if reasons:
        return TransitionDecision("denied", tuple(reasons), tuple(sorted(supplied)))
    return TransitionDecision("allowed", ("transition_requirements_satisfied",), tuple(sorted(supplied)))
