from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.founder_acceptance_session import FounderAcceptanceSession
from adapters.gsd_bounded_continuation import (
    BoundedContinuationController,
    BoundedContinuationError,
    BoundedTask,
    DeterministicCheck,
)


PHASE = {
    "phase_id": "P050",
    "specification_ref": "gsd-master-risk-based-one-shot-gate-orchestration",
    "specification_hash": "sha256:63347f3128151074fe5768c37668234322e9885838f374f5850744b8edd0218a",
    "review_required": True,
    "review_provider_ref": "core-independent-reviewer via AGY",
}


def _session(tmp_path: Path) -> tuple[Path, dict, dict]:
    path = tmp_path / "session.json"
    FounderAcceptanceSession(path).open(
        session_id="test-p050-session",
        authority_subject="Pieter van Rooyen — Platform Founder/Core Owner",
        authentication={"method": "existing-governance-evidence", "credential_ref": "test", "verified_at": "2026-10-18T00:00:00Z", "verification_ref": "test"},
        authority_basis_refs=["test-authority"],
        authority_roles={"owner": "Pieter", "implementer": "Pieter", "acceptance": "Pieter"},
        phase_ids=["P050"],
        allowed_actions=["authorize-bounded-task"],
        specification_bindings=[PHASE],
        exclusions=["P051+", "production"],
        opened_at="2026-10-18T00:00:00Z",
    )
    prepared = FounderAcceptanceSession(path).prepare({
        "decision_id": "test-t002-auth",
        **PHASE,
        "action": "authorize-bounded-task",
        "exclusions": ["P051+", "production"],
        "independent_review": {"required": True, "provider_ref": PHASE["review_provider_ref"]},
    })
    confirmation = FounderAcceptanceSession(path).confirm(prepared, "yes")
    return path, prepared, confirmation


def _task(task_id: str, status: str = "SUCCEEDED") -> BoundedTask:
    return BoundedTask(task_id, lambda: {"status": status})


def _check(check_id: str, status: str = "PASSED") -> DeterministicCheck:
    return DeterministicCheck(check_id, lambda: {"status": status})


def test_success_stops_at_independent_review_boundary(tmp_path: Path) -> None:
    path, prepared, confirmation = _session(tmp_path)
    evidence = tmp_path / "run.json"
    result = BoundedContinuationController(path).run(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=[_task("T002-001"), _task("T002-002")],
        checks=[_check("deterministic-suite")],
        evidence_path=evidence,
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
        run_id="p050-t002-test-run",
    )
    assert result["status"] == "REVIEW_PENDING"
    assert result["provider_invocation"] == "NOT_STARTED"
    assert result["acceptance"] == "NOT_GRANTED"
    assert json.loads(evidence.read_text())["evidence_digest"].startswith("sha256:")


def test_failed_task_blocks_later_tasks(tmp_path: Path) -> None:
    path, prepared, confirmation = _session(tmp_path)
    seen: list[str] = []
    result = BoundedContinuationController(path).run(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=[BoundedTask("bad", lambda: (seen.append("bad") or {"status": "FAILED"})), BoundedTask("later", lambda: (seen.append("later") or {"status": "SUCCEEDED"}))],
        checks=[_check("suite")],
        evidence_path=tmp_path / "run.json",
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
    )
    assert result["status"] == "BLOCKED"
    assert seen == ["bad"]
    assert "task failed" in result["stop_reason"]


def test_failed_check_blocks_review_request(tmp_path: Path) -> None:
    path, prepared, confirmation = _session(tmp_path)
    result = BoundedContinuationController(path).run(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=[_task("task")],
        checks=[_check("suite", "FAILED")],
        evidence_path=tmp_path / "run.json",
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
    )
    assert result["status"] == "BLOCKED"
    assert "deterministic check failed" in result["stop_reason"]
    assert "review_request" not in result


def test_mismatched_authorization_fails_closed(tmp_path: Path) -> None:
    path, prepared, confirmation = _session(tmp_path)
    tampered = dict(prepared)
    tampered["phase_id"] = "P051"
    with pytest.raises(BoundedContinuationError):
        BoundedContinuationController(path).run(
            authorization={"prepared": tampered, "confirmation": confirmation},
            tasks=[_task("task")],
            checks=[_check("suite")],
            evidence_path=tmp_path / "run.json",
            review_required=True,
            review_provider_ref=PHASE["review_provider_ref"],
        )


def test_evidence_is_not_overwritten(tmp_path: Path) -> None:
    path, prepared, confirmation = _session(tmp_path)
    evidence = tmp_path / "run.json"
    kwargs = dict(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=[_task("task")],
        checks=[_check("suite")],
        evidence_path=evidence,
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
    )
    BoundedContinuationController(path).run(**kwargs)
    with pytest.raises(BoundedContinuationError, match="overwrite"):
        BoundedContinuationController(path).run(**kwargs)
