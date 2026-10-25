"""Validation and control derivation for governance-profile.v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "governance-profile.v1.schema.json"
PROFILES = ("documentation", "design", "implementation", "activation")
BOUNDARY_CONTROLS = {
    "publication": {"independent_review", "explicit_implementation_authorization"},
    "runtime_identity": {"independent_review", "explicit_implementation_authorization", "rollback_plan"},
    "production_control": {"independent_review", "explicit_implementation_authorization", "production_activation_authorization", "rollback_plan"},
    "production_environment": {"independent_review", "explicit_implementation_authorization", "rollback_plan"},
    "sensitive_data": {"impact_assessment"},
    "internal": set(),
}


class GovernanceProfileError(ValueError):
    """Raised when a governance profile is structurally or semantically unsafe."""


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_governance_profile(profile: Mapping[str, Any]) -> None:
    errors = sorted(Draft202012Validator(_schema()).iter_errors(profile), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "root"
        raise GovernanceProfileError(f"invalid governance-profile.v1 at {location}: {errors[0].message}")

    decisions = profile["decisions"]
    ids = [decision["decision_id"] for decision in decisions]
    if len(ids) != len(set(ids)):
        raise GovernanceProfileError("decision_id values must be unique")
    types = [decision["type"] for decision in decisions]
    if len(types) != len(set(types)):
        raise GovernanceProfileError("decision type values must be unique")

    if profile["review"]["required"] and profile["review"]["status"] == "not_required":
        raise GovernanceProfileError("required review cannot have status not_required")
    if profile["review"]["status"] == "complete" and not profile["review"].get("reviewer_ref"):
        raise GovernanceProfileError("complete review requires reviewer_ref")
    if profile["review"]["status"] == "incomplete_review" and not profile["review"].get("escalation_ref"):
        raise GovernanceProfileError("incomplete review requires escalation_ref")

    by_type = {decision["type"]: decision for decision in decisions}
    accepted = {kind for kind, decision in by_type.items() if decision["status"] == "accepted"}
    if "production_activation" in accepted and "implementation_authorization" not in accepted:
        raise GovernanceProfileError("production activation requires implementation authorization")
    if "implementation_authorization" in accepted and "contract_approval" not in accepted:
        raise GovernanceProfileError("implementation authorization requires contract approval")
    if profile["work_profile"] == "activation" and "production_activation" not in accepted:
        raise GovernanceProfileError("activation profile requires production activation authorization")
    if profile["closeout"]["status"] == "closed" and not profile["closeout"].get("canonical_summary_ref"):
        raise GovernanceProfileError("closed profile requires canonical summary reference")


def required_controls(profile: Mapping[str, Any]) -> set[str]:
    """Return the union of work-profile and impact-boundary controls."""
    validate_governance_profile(profile)
    controls: set[str] = set()
    if profile["work_profile"] in {"design", "implementation", "activation"}:
        controls.add("owner_or_accountable_review")
    if profile["work_profile"] in {"implementation", "activation"}:
        controls.update({"tests", "code_or_artifact_review"})
    if profile["work_profile"] == "activation":
        controls.update({"explicit_implementation_authorization", "production_activation_authorization", "rollback_plan"})
    for boundary in profile["impact_boundaries"]:
        controls.update(BOUNDARY_CONTROLS[boundary])
    return controls


def independent_review_required(
    profile: Mapping[str, Any], *, factors: Mapping[str, str] | None = None
) -> bool:
    """Derive the independent-review gate from boundary and risk, not defaults."""
    controls = required_controls(profile)
    if profile["review"]["required"]:
        return True
    if "independent_review" in controls:
        return True
    if factors is not None and any(level == "high" for level in factors.values()):
        return True
    if factors is None:
        return bool(profile["review"]["required"])
    return False
