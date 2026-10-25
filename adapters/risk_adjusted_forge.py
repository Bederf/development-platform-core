"""Fail-closed composition of GSD risk, governance controls, and Forge requests."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .forge_request import ForgeRequestAdapter, ForgeRequestError
from .governance_profile import (
    GovernanceProfileError,
    independent_review_required,
    required_controls,
    validate_governance_profile,
)
from .gsd_execution_model import GsdExecutionModelError, select_profile


ROOT = Path(__file__).parents[1]
REQUEST_SCHEMA_PATH = ROOT / "contracts" / "risk-adjusted-verification-request.v1.schema.json"


class RiskAdjustedForgeError(ValueError):
    """Raised when risk-adjusted Forge composition cannot be made safely."""


CONTROL_CHECKS = {
    "owner_or_accountable_review": "governance-owner-review",
    "independent_review": "independent-review",
    "explicit_implementation_authorization": "implementation-authorization",
    "production_activation_authorization": "production-activation-authorization",
    "rollback_plan": "rollback-plan",
    "tests": "tests",
    "code_or_artifact_review": "code-or-artifact-review",
    "impact_assessment": "impact-assessment",
}


@dataclass(frozen=True)
class RiskAdjustedForgePlan:
    """Typed, auditable plan carried inside a ``forge-adapter.v1`` request."""

    request: dict[str, Any]
    governance_profile: dict[str, Any]

    @property
    def verification_request(self) -> dict[str, Any]:
        return self.request["verification_request"]

    @property
    def required_controls(self) -> tuple[str, ...]:
        return tuple(self.verification_request["required_controls"])

    @property
    def required_checks(self) -> tuple[str, ...]:
        return tuple(self.verification_request["required_checks"])


def _validate_request(value: Mapping[str, Any]) -> None:
    schema = json.loads(REQUEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(item) for item in errors[0].path) or "request"
        raise RiskAdjustedForgeError(f"invalid risk-adjusted verification request at {location}: {errors[0].message}")


def build_risk_adjusted_forge_request(
    *,
    project_id: str,
    phase_id: str,
    work_id: str,
    request_id: str,
    verification_attempt_id: str,
    repository: str,
    baseline: str,
    factors: Mapping[str, str],
    governance_profile: Mapping[str, Any],
    authority_ref: str,
    required_artifacts: list[str],
) -> RiskAdjustedForgePlan:
    """Build a typed Forge request from one correlated risk/governance input set."""
    try:
        validate_governance_profile(governance_profile)
        execution_profile = select_profile(factors)
        controls = sorted(required_controls(governance_profile))
    except (GovernanceProfileError, GsdExecutionModelError) as exc:
        raise RiskAdjustedForgeError(f"risk/governance composition denied: {exc}") from exc

    for value, name in (
        (phase_id, "phase_id"),
        (work_id, "work_id"),
        (verification_attempt_id, "verification_attempt_id"),
        (repository, "repository"),
        (baseline, "baseline"),
        (authority_ref, "authority_ref"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise RiskAdjustedForgeError(f"{name} must be a non-empty string")
    if not isinstance(factors, Mapping) or set(factors) != {"scope", "blast_radius", "risk", "dependencies", "architecture_impact"}:
        raise RiskAdjustedForgeError("risk factors must contain exactly the five GSD factor names")
    if not isinstance(required_artifacts, list) or not required_artifacts or any(not isinstance(item, str) or not item.strip() for item in required_artifacts):
        raise RiskAdjustedForgeError("at least one required artifact path is required")
    _validate_artifact_paths(required_artifacts)

    profile_ref = f"{governance_profile['profile_id']}@{governance_profile['version']}"
    try:
        checks = [CONTROL_CHECKS[control] for control in controls]
    except KeyError as exc:
        raise RiskAdjustedForgeError(f"no Forge check mapping exists for governance control: {exc.args[0]}") from exc

    inner = {
        "schema": "risk-adjusted-verification-request.v1",
        "project_id": project_id,
        "phase_id": phase_id,
        "work_id": work_id,
        "request_id": request_id,
        "verification_attempt_id": verification_attempt_id,
        "repository": repository,
        "baseline": baseline,
        "execution_profile": execution_profile,
        "risk_factors": deepcopy(dict(factors)),
        "governance_profile_ref": profile_ref,
        "required_controls": controls,
        "required_checks": checks,
        "independent_review_required": independent_review_required(governance_profile, factors=factors),
        "required_artifacts": list(dict.fromkeys(required_artifacts)),
        "authority_ref": authority_ref,
        "verification_operation": "finish",
        "independence": "forge-provider",
    }
    _validate_request(inner)

    try:
        request = ForgeRequestAdapter().build(
            operation="finish",
            project_id=project_id,
            request_id=request_id,
            session_id=None,
            verification_request=inner,
        )
    except ForgeRequestError as exc:
        raise RiskAdjustedForgeError(f"Forge request construction denied: {exc}") from exc
    return RiskAdjustedForgePlan(request=request, governance_profile=deepcopy(dict(governance_profile)))


def _validate_artifact_paths(paths: list[str]) -> None:
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RiskAdjustedForgeError(f"required artifact path must remain repository-relative: {path!r}")


def validate_risk_adjusted_forge_request(
    request: Mapping[str, Any], *, governance_profile: Mapping[str, Any]
) -> None:
    """Validate outer and inner request identity before provider execution."""
    if request.get("schema") != "forge-adapter.v1" or request.get("operation") != "finish":
        raise RiskAdjustedForgeError("risk-adjusted verification requires a forge-adapter.v1 finish request")
    inner = request.get("verification_request")
    if not isinstance(inner, Mapping):
        raise RiskAdjustedForgeError("typed risk-adjusted verification_request is required")
    if request.get("request_id") != inner.get("request_id"):
        raise RiskAdjustedForgeError("outer and inner request identity mismatch")
    if request.get("project_id") != inner.get("project_id"):
        raise RiskAdjustedForgeError("outer and inner project identity mismatch")
    _validate_request(inner)
    try:
        validate_governance_profile(governance_profile)
        expected_profile_ref = f"{governance_profile['profile_id']}@{governance_profile['version']}"
        expected_profile = select_profile(inner["risk_factors"])
        expected_controls = sorted(required_controls(governance_profile))
    except (GovernanceProfileError, GsdExecutionModelError) as exc:
        raise RiskAdjustedForgeError(f"governance context cannot be validated: {exc}") from exc
    if inner["governance_profile_ref"] != expected_profile_ref:
        raise RiskAdjustedForgeError("governance profile reference mismatch")
    if inner["execution_profile"] != expected_profile:
        raise RiskAdjustedForgeError("execution profile does not match risk factors")
    if inner["required_controls"] != expected_controls:
        raise RiskAdjustedForgeError("required controls do not match governance profile")
    expected_checks = [CONTROL_CHECKS[control] for control in expected_controls]
    if inner["required_checks"] != expected_checks:
        raise RiskAdjustedForgeError("required checks do not match governance controls")
    expected_review = independent_review_required(governance_profile, factors=inner["risk_factors"])
    if inner["independent_review_required"] != expected_review:
        raise RiskAdjustedForgeError("independent-review requirement does not match risk and governance")
    _validate_artifact_paths(inner["required_artifacts"])


def render_forge_manifest(plan: RiskAdjustedForgePlan, check_commands: Mapping[str, str]) -> dict[str, Any]:
    """Project an approved plan into provider manifest data without executing Forge."""
    validate_risk_adjusted_forge_request(plan.request, governance_profile=plan.governance_profile)
    missing = [check for check in plan.required_checks if check not in check_commands]
    if missing:
        raise RiskAdjustedForgeError(f"missing provider command mapping for checks: {', '.join(missing)}")
    return {
        "v": 1,
        "project": plan.verification_request["project_id"],
        "methodology": "risk-adjusted-core-v1",
        "startup_checks": [],
        "finish_checks": [
            {"name": check, "command": check_commands[check], "required": True, "timeout_seconds": 30}
            for check in plan.required_checks
        ],
        "required_artifacts": list(plan.verification_request["required_artifacts"]),
    }
