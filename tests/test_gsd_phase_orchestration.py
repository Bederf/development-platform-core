from __future__ import annotations

from pathlib import Path

import pytest

from adapters.founder_acceptance_session import FounderAcceptanceSession
from adapters.gsd_phase_orchestration import (
    PhaseCheck,
    PhaseOrchestrationController,
    PhaseOrchestrationError,
    PhaseTask,
)


PHASE = {
    "phase_id": "P056",
    "specification_ref": "gsd-master-phase-level-one-shot-orchestration",
    "specification_hash": "sha256:" + "b" * 64,
    "review_required": True,
    "review_provider_ref": "core-independent-reviewer via AGY",
}
EXCLUSIONS = ["production", "consumer activation", "later phases"]


def _authorization(tmp_path: Path) -> tuple[Path, dict, dict]:
    path = tmp_path / "session.json"
    session = FounderAcceptanceSession(path)
    session.open(
        session_id="p056-session",
        authority_subject="Pieter van Rooyen — Platform Founder/Core Owner",
        authentication={"method": "existing-governance-evidence", "credential_ref": "test", "verified_at": "2026-10-18T00:00:00Z", "verification_ref": "test"},
        authority_basis_refs=["test-authority"],
        authority_roles={"owner": "Pieter", "implementer": "Pieter", "acceptance": "Pieter"},
        phase_ids=["P056"],
        allowed_actions=["authorize-phase-execution"],
        specification_bindings=[PHASE],
        exclusions=EXCLUSIONS,
        opened_at="2026-10-18T00:00:00Z",
    )
    prepared = session.prepare({
        "decision_id": "p056-phase-execution",
        **PHASE,
        "action": "authorize-phase-execution",
        "exclusions": EXCLUSIONS,
        "independent_review": {"required": True, "provider_ref": PHASE["review_provider_ref"]},
    })
    return path, prepared, session.confirm(prepared, "yes")


def _task(task_id: str, depends_on: tuple[str, ...] = (), status: str = "SUCCEEDED") -> PhaseTask:
    return PhaseTask(task_id, depends_on, lambda: {"status": status})


def _check(check_id: str, status: str = "PASSED") -> PhaseCheck:
    return PhaseCheck(check_id, lambda: {"status": status})


def _review(run_id: str) -> tuple[dict, dict]:
    result = {
        "schema": "code-review-result.v1",
        "review_id": "p056-review-1",
        "independence": "independent",
        "disposition": "PASS",
        "providers": {"selected": [PHASE["review_provider_ref"]]},
        "evidence": [{"kind": "run", "ref": "run"}, {"kind": "test", "ref": "test"}, {"kind": "policy", "ref": "policy"}],
    }
    cycle = {"schema": "review-cycle.v1", "status": "PASSED", "revision_ref": run_id, "review_result_ref": result["review_id"]}
    return result, cycle


def test_phase_runs_dependency_graph_once_and_prepares_phase_acceptance(tmp_path: Path) -> None:
    session_path, prepared, confirmation = _authorization(tmp_path)
    seen: list[str] = []
    tasks = [
        PhaseTask("build", ("discover",), lambda: (seen.append("build") or {"status": "SUCCEEDED"})),
        PhaseTask("discover", (), lambda: (seen.append("discover") or {"status": "SUCCEEDED"})),
        PhaseTask("test", ("build",), lambda: (seen.append("test") or {"status": "SUCCEEDED"})),
    ]
    run = PhaseOrchestrationController(session_path, phase_id="P056").run(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=tasks,
        checks=[_check("qualification")],
        evidence_path=tmp_path / "phase-run.json",
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
        run_id="p056-run-1",
    )
    assert seen == ["discover", "build", "test"]
    assert run["status"] == "REVIEW_PENDING"
    assert run["review_request"]["task_ref"] == "P056"
    review, cycle = _review(run["run_id"])
    boundary = PhaseOrchestrationController(session_path, phase_id="P056").prepare_phase_acceptance(
        run=run,
        acceptance_evidence_path=tmp_path / "phase-acceptance.json",
        review_result=review,
        review_cycle=cycle,
    )
    assert boundary.status == "ACCEPTANCE_PENDING"
    assert boundary.prepared_acceptance["schema"] == "gsd-phase-acceptance-boundary.v1"
    assert boundary.prepared_acceptance["acceptance_granted"] is False
    assert "task_id" not in boundary.prepared_acceptance


def test_phase_runs_registered_review_and_stops_at_acceptance_boundary(tmp_path: Path) -> None:
    session_path, prepared, confirmation = _authorization(tmp_path)

    def review_executor(request: dict) -> dict:
        result, cycle = _review(request["revision_ref"])
        return {"review_result": result, "review_cycle": cycle}

    run = PhaseOrchestrationController(session_path, phase_id="P056").run(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=[_task("implementation")],
        checks=[_check("qualification")],
        evidence_path=tmp_path / "auto-review.json",
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
        run_id="p056-auto-review",
        review_executor=review_executor,
    )

    assert run["status"] == "ACCEPTANCE_PENDING"
    assert run["review_result"]["disposition"] == "PASS"
    assert run["stop_reason"] == "independent review completed; separate phase acceptance decision is required"


def test_failed_registered_review_blocks_after_review_not_before_it(tmp_path: Path) -> None:
    session_path, prepared, confirmation = _authorization(tmp_path)

    def review_executor(request: dict) -> dict:
        result, cycle = _review(request["revision_ref"])
        result["disposition"] = "CHANGES_REQUIRED"
        cycle["status"] = "ESCALATED"
        cycle["outcome"] = "CHANGES_REQUIRED"
        return {"review_result": result, "review_cycle": cycle}

    run = PhaseOrchestrationController(session_path, phase_id="P056").run(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=[_task("implementation")],
        checks=[_check("qualification")],
        evidence_path=tmp_path / "failed-review.json",
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
        review_executor=review_executor,
    )

    assert run["status"] == "BLOCKED"
    assert "CHANGES_REQUIRED" in run["stop_reason"]


def test_failed_task_stops_remaining_dag(tmp_path: Path) -> None:
    session_path, prepared, confirmation = _authorization(tmp_path)
    seen: list[str] = []
    run = PhaseOrchestrationController(session_path, phase_id="P056").run(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=[
            PhaseTask("bad", (), lambda: (seen.append("bad") or {"status": "FAILED"})),
            PhaseTask("later", ("bad",), lambda: (seen.append("later") or {"status": "SUCCEEDED"})),
        ],
        checks=[_check("qualification")],
        evidence_path=tmp_path / "phase-run.json",
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
    )
    assert seen == ["bad"]
    assert run["status"] == "BLOCKED"
    assert "phase task failed" in run["stop_reason"]


def test_failed_check_blocks_review_and_acceptance(tmp_path: Path) -> None:
    session_path, prepared, confirmation = _authorization(tmp_path)
    run = PhaseOrchestrationController(session_path, phase_id="P056").run(
        authorization={"prepared": prepared, "confirmation": confirmation},
        tasks=[_task("implementation")],
        checks=[_check("qualification", "FAILED")],
        evidence_path=tmp_path / "phase-run.json",
        review_required=True,
        review_provider_ref=PHASE["review_provider_ref"],
    )
    assert run["status"] == "BLOCKED"
    assert "review_request" not in run
    with pytest.raises(PhaseOrchestrationError, match="has not reached"):
        PhaseOrchestrationController(session_path, phase_id="P056").prepare_phase_acceptance(
            run=run, acceptance_evidence_path=tmp_path / "acceptance.json"
        )


def test_cycle_and_wrong_authorization_fail_closed(tmp_path: Path) -> None:
    session_path, prepared, confirmation = _authorization(tmp_path)
    controller = PhaseOrchestrationController(session_path, phase_id="P056")
    with pytest.raises(PhaseOrchestrationError, match="cycle"):
        controller.run(
            authorization={"prepared": prepared, "confirmation": confirmation},
            tasks=[_task("a", ("b",)), _task("b", ("a",))],
            checks=[_check("check")],
            evidence_path=tmp_path / "cycle.json",
            review_required=True,
            review_provider_ref=PHASE["review_provider_ref"],
        )
    tampered = dict(prepared)
    tampered["action"] = "authorize-bounded-task"
    with pytest.raises(PhaseOrchestrationError, match="not for this phase"):
        controller.run(
            authorization={"prepared": tampered, "confirmation": confirmation},
            tasks=[_task("a")],
            checks=[_check("check")],
            evidence_path=tmp_path / "wrong.json",
            review_required=True,
            review_provider_ref=PHASE["review_provider_ref"],
        )


def test_phase_evidence_is_not_overwritten(tmp_path: Path) -> None:
    session_path, prepared, confirmation = _authorization(tmp_path)
    controller = PhaseOrchestrationController(session_path, phase_id="P056")
    kwargs = {
        "authorization": {"prepared": prepared, "confirmation": confirmation},
        "tasks": [_task("implementation")],
        "checks": [_check("qualification")],
        "evidence_path": tmp_path / "phase-run.json",
        "review_required": True,
        "review_provider_ref": PHASE["review_provider_ref"],
    }
    controller.run(**kwargs)
    with pytest.raises(PhaseOrchestrationError, match="overwrite"):
        controller.run(**kwargs)
