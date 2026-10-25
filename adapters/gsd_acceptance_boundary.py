"""Prepare, but never grant, the bounded GSD acceptance boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any


class AcceptanceBoundaryError(ValueError):
    """Raised when acceptance-boundary evidence is incomplete or unbound."""


@dataclass(frozen=True)
class AcceptanceBoundary:
    """A content-bound acceptance decision waiting for its authority."""

    status: str
    acceptance_required: bool
    review_required: bool
    policy_basis: str
    reason: str
    prepared_acceptance: dict[str, Any] | None


def _digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("prepared_digest", None)
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def prepare_acceptance_boundary(
    *,
    phase_id: str,
    task_id: str,
    session_id: str,
    session_digest: str,
    run_id: str,
    run_evidence_digest: str,
    review_required: bool,
    review_provider_ref: str,
    technical_verification_passed: bool,
    policy_basis: str,
    review_result: Mapping[str, Any] | None = None,
    review_cycle: Mapping[str, Any] | None = None,
) -> AcceptanceBoundary:
    """Prepare the next boundary from risk policy and evidence.

    A positive review is evidence only.  This function never returns an
    accepted/closed status and never authorizes a later task or phase.
    """

    for value, name in (
        (phase_id, "phase_id"),
        (task_id, "task_id"),
        (session_id, "session_id"),
        (session_digest, "session_digest"),
        (run_id, "run_id"),
        (run_evidence_digest, "run_evidence_digest"),
        (policy_basis, "policy_basis"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise AcceptanceBoundaryError(f"{name} is required")
    if not isinstance(review_required, bool) or not isinstance(technical_verification_passed, bool):
        raise AcceptanceBoundaryError("review_required and technical_verification_passed must be boolean")
    if review_required and (not isinstance(review_provider_ref, str) or not review_provider_ref.strip()):
        raise AcceptanceBoundaryError("review provider is required by the review policy")
    if not technical_verification_passed:
        return AcceptanceBoundary(
            status="BLOCKED",
            acceptance_required=False,
            review_required=review_required,
            policy_basis=policy_basis,
            reason="technical verification has not passed",
            prepared_acceptance=None,
        )

    if review_required and review_result is None:
        return AcceptanceBoundary(
            status="REVIEW_PENDING",
            acceptance_required=False,
            review_required=True,
            policy_basis=policy_basis,
            reason="independent review evidence is required before acceptance preparation",
            prepared_acceptance=None,
        )

    if review_required:
        _validate_review(review_result, review_cycle, run_id, review_provider_ref)
        review_disposition = str(review_result["disposition"])
    else:
        review_disposition = "NOT_REQUIRED_BY_RISK_POLICY"

    prepared: dict[str, Any] = {
        "schema": "gsd-acceptance-boundary.v1",
        "decision_id": f"{phase_id.lower()}-{task_id.lower()}-acceptance",
        "phase_id": phase_id,
        "task_id": task_id,
        "session_id": session_id,
        "session_digest": session_digest,
        "run_id": run_id,
        "run_evidence_digest": run_evidence_digest,
        "review_policy": {
            "required": review_required,
            "provider_ref": review_provider_ref if review_required else "not-required-by-risk-policy",
            "basis": policy_basis,
        },
        "review_disposition": review_disposition,
        "acceptance_required": True,
        "acceptance_granted": False,
        "later_authority_granted": False,
    }
    prepared["prepared_digest"] = _digest(prepared)
    return AcceptanceBoundary(
        status="ACCEPTANCE_PENDING",
        acceptance_required=True,
        review_required=review_required,
        policy_basis=policy_basis,
        reason=(
            "independent review passed; separate acceptance decision is required"
            if review_required
            else "technical verification passed under non-required-review policy; separate acceptance decision is required"
        ),
        prepared_acceptance=prepared,
    )


def prepare_phase_acceptance_boundary(
    *,
    phase_id: str,
    session_id: str,
    session_digest: str,
    run_id: str,
    run_evidence_digest: str,
    review_required: bool,
    review_provider_ref: str,
    technical_verification_passed: bool,
    policy_basis: str,
    review_result: Mapping[str, Any] | None = None,
    review_cycle: Mapping[str, Any] | None = None,
    evidence_refs: Sequence[str] = (),
) -> AcceptanceBoundary:
    """Prepare one phase-level acceptance decision, never task acceptance."""

    for value, name in (
        (phase_id, "phase_id"),
        (session_id, "session_id"),
        (session_digest, "session_digest"),
        (run_id, "run_id"),
        (run_evidence_digest, "run_evidence_digest"),
        (policy_basis, "policy_basis"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise AcceptanceBoundaryError(f"{name} is required")
    if not isinstance(review_required, bool) or not isinstance(technical_verification_passed, bool):
        raise AcceptanceBoundaryError("review_required and technical_verification_passed must be boolean")
    if review_required and (not isinstance(review_provider_ref, str) or not review_provider_ref.strip()):
        raise AcceptanceBoundaryError("review provider is required by the review policy")
    if not technical_verification_passed:
        return AcceptanceBoundary("BLOCKED", False, review_required, policy_basis, "technical verification has not passed", None)
    if review_required and review_result is None:
        return AcceptanceBoundary("REVIEW_PENDING", False, True, policy_basis, "independent review evidence is required before phase acceptance preparation", None)
    if review_required:
        _validate_review(review_result, review_cycle, run_id, review_provider_ref)
        disposition = str(review_result["disposition"])
    else:
        disposition = "NOT_REQUIRED_BY_RISK_POLICY"
    refs = [ref for ref in evidence_refs if isinstance(ref, str) and ref]
    prepared: dict[str, Any] = {
        "schema": "gsd-phase-acceptance-boundary.v1",
        "decision_id": f"{phase_id.lower()}-phase-acceptance",
        "phase_id": phase_id,
        "session_id": session_id,
        "session_digest": session_digest,
        "run_id": run_id,
        "run_evidence_digest": run_evidence_digest,
        "review_policy": {
            "required": review_required,
            "provider_ref": review_provider_ref if review_required else "not-required-by-risk-policy",
            "basis": policy_basis,
        },
        "review_disposition": disposition,
        "acceptance_required": True,
        "acceptance_granted": False,
        "later_authority_granted": False,
        "evidence_refs": refs,
    }
    prepared["prepared_digest"] = _digest(prepared)
    return AcceptanceBoundary(
        "ACCEPTANCE_PENDING",
        True,
        review_required,
        policy_basis,
        "independent review passed; separate phase acceptance decision is required" if review_required else "technical verification passed under non-required-review policy; separate phase acceptance decision is required",
        prepared,
    )


def _validate_review(
    result: Mapping[str, Any] | None,
    cycle: Mapping[str, Any] | None,
    run_id: str,
    provider_ref: str,
) -> None:
    if not isinstance(result, Mapping) or not isinstance(cycle, Mapping):
        raise AcceptanceBoundaryError("review result and cycle evidence are required")
    if result.get("schema") != "code-review-result.v1":
        raise AcceptanceBoundaryError("review result schema is invalid")
    if result.get("independence") != "independent":
        raise AcceptanceBoundaryError("review result is not independent")
    if result.get("disposition") not in {"PASS", "PASS_WITH_ADVISORIES"}:
        raise AcceptanceBoundaryError("review result did not pass")
    if cycle.get("schema") != "review-cycle.v1" or cycle.get("status") != "PASSED":
        raise AcceptanceBoundaryError("review cycle is not passed")
    if cycle.get("revision_ref") != run_id:
        raise AcceptanceBoundaryError("review cycle is not bound to the run")
    if cycle.get("review_result_ref") != result.get("review_id"):
        raise AcceptanceBoundaryError("review cycle does not reference the review result")
    providers = result.get("providers")
    selected = providers.get("selected") if isinstance(providers, Mapping) else None
    considered = providers.get("considered") if isinstance(providers, Mapping) else None
    route_matches = (
        isinstance(selected, list)
        and bool(selected)
        and (
            provider_ref in selected
            or (
                provider_ref == "core-independent-reviewer via AGY"
                and isinstance(considered, list)
                and "agy" in {str(item).lower() for item in considered}
            )
        )
    )
    if not route_matches:
        raise AcceptanceBoundaryError("review result is not bound to the selected provider route")
    evidence = result.get("evidence")
    if not isinstance(evidence, list) or len(evidence) < 3:
        raise AcceptanceBoundaryError("review result evidence is incomplete")
