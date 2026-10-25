from __future__ import annotations

import pytest

from adapters.gsd_acceptance_boundary import (
    AcceptanceBoundaryError,
    prepare_acceptance_boundary,
    prepare_phase_acceptance_boundary,
)


COMMON = {
    "phase_id": "P050",
    "task_id": "P050-T003",
    "session_id": "session-p050",
    "session_digest": "sha256:" + "a" * 64,
    "run_id": "p050-t003-run",
    "run_evidence_digest": "sha256:" + "b" * 64,
    "review_provider_ref": "core-independent-reviewer via AGY",
    "technical_verification_passed": True,
    "policy_basis": "validated phase risk policy",
}


def _review(disposition: str = "PASS") -> tuple[dict, dict]:
    result = {
        "schema": "code-review-result.v1",
        "review_id": "review-1",
        "independence": "independent",
        "disposition": disposition,
        "providers": {"selected": ["core-independent-reviewer via AGY"]},
        "evidence": [{"kind": "a", "ref": "a"}, {"kind": "b", "ref": "b"}, {"kind": "c", "ref": "c"}],
    }
    cycle = {
        "schema": "review-cycle.v1",
        "status": "PASSED",
        "revision_ref": "p050-t003-run",
        "review_result_ref": "review-1",
    }
    return result, cycle


def test_required_review_stops_before_review_result() -> None:
    boundary = prepare_acceptance_boundary(**COMMON, review_required=True, review_result=None)
    assert boundary.status == "REVIEW_PENDING"
    assert boundary.prepared_acceptance is None


def test_positive_required_review_prepares_separate_acceptance() -> None:
    result, cycle = _review("PASS_WITH_ADVISORIES")
    boundary = prepare_acceptance_boundary(**COMMON, review_required=True, review_result=result, review_cycle=cycle)
    assert boundary.status == "ACCEPTANCE_PENDING"
    assert boundary.prepared_acceptance["acceptance_required"] is True
    assert boundary.prepared_acceptance["acceptance_granted"] is False
    assert boundary.prepared_acceptance["later_authority_granted"] is False
    assert boundary.prepared_acceptance["prepared_digest"].startswith("sha256:")


def test_low_risk_path_records_policy_and_prepares_acceptance() -> None:
    boundary = prepare_acceptance_boundary(**COMMON, review_required=False, review_result=None)
    assert boundary.status == "ACCEPTANCE_PENDING"
    assert boundary.prepared_acceptance["review_disposition"] == "NOT_REQUIRED_BY_RISK_POLICY"
    assert boundary.prepared_acceptance["review_policy"]["basis"] == "validated phase risk policy"


def test_failed_technical_verification_blocks_every_path() -> None:
    values = dict(COMMON, technical_verification_passed=False)
    boundary = prepare_acceptance_boundary(**values, review_required=False, review_result=None)
    assert boundary.status == "BLOCKED"
    assert boundary.prepared_acceptance is None


def test_unbound_or_failed_review_fails_closed() -> None:
    result, cycle = _review("PASS")
    cycle["revision_ref"] = "different-run"
    with pytest.raises(AcceptanceBoundaryError, match="bound to the run"):
        prepare_acceptance_boundary(**COMMON, review_required=True, review_result=result, review_cycle=cycle)

    result, cycle = _review("CHANGES_REQUIRED")
    with pytest.raises(AcceptanceBoundaryError, match="did not pass"):
        prepare_acceptance_boundary(**COMMON, review_required=True, review_result=result, review_cycle=cycle)


def test_phase_acceptance_binds_registered_agy_route_to_selected_model() -> None:
    result, cycle = _review("PASS")
    result["providers"] = {
        "considered": ["agy"],
        "selected": ["gemini-3.8-flash-low"],
        "skipped": [],
    }
    boundary = prepare_phase_acceptance_boundary(
        phase_id="P056",
        session_id="session",
        session_digest="sha256:" + "a" * 64,
        run_id="p050-t003-run",
        run_evidence_digest="sha256:" + "b" * 64,
        review_required=True,
        review_provider_ref="core-independent-reviewer via AGY",
        technical_verification_passed=True,
        policy_basis="validated phase risk policy",
        review_result=result,
        review_cycle=cycle,
        evidence_refs=["run", "review", "cycle"],
    )
    assert boundary.status == "ACCEPTANCE_PENDING"
