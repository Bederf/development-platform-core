import json
from pathlib import Path

import pytest

from adapters.gsd_execution_admission import AdmissionController, AdmissionError, BoundGraph, GraphTask
from adapters.gsd_execution_journal import JournalStore
from adapters.gsd_execution_state import TaskState


def graph():
    return BoundGraph(
        "sha256:spec",
        "graph-1",
        (GraphTask("a"), GraphTask("b", ("a",)), GraphTask("c")),
    )


def states(**overrides):
    result = {"a": TaskState.PENDING, "b": TaskState.PENDING, "c": TaskState.PENDING}
    result.update(overrides)
    return result


def test_readiness_is_controller_derived_and_deterministically_ordered(tmp_path):
    controller = AdmissionController(JournalStore(tmp_path / "journal.sqlite"))
    assert controller.ready_tasks(graph(), states()) == ("a", "c")
    assert controller.ready_tasks(graph(), states(), caller_ready=("a", "c")) == ("a", "c")


def test_failed_unknown_or_blocked_predecessors_prevent_readiness(tmp_path):
    controller = AdmissionController(JournalStore(tmp_path / "journal.sqlite"))
    for state in (TaskState.FAILED, TaskState.CANCELLED, TaskState.BLOCKED, TaskState.UNKNOWN):
        assert "b" not in controller.ready_tasks(graph(), states(a=state))
    assert "b" not in controller.ready_tasks(
        graph(), states(a=TaskState.SUCCEEDED),
        attempt_states={"a": __import__("adapters.gsd_execution_state", fromlist=["AttemptState"]).AttemptState.FAILED},
    )


def test_caller_readiness_and_graph_divergence_fail_closed(tmp_path):
    controller = AdmissionController(JournalStore(tmp_path / "journal.sqlite"))
    with pytest.raises(AdmissionError, match="caller-supplied"):
        controller.ready_tasks(graph(), states(), caller_ready=("b",))
    with pytest.raises(AdmissionError, match="diverges"):
        controller.ready_tasks(graph(), {"a": TaskState.PENDING})


def test_graph_unknown_predecessor_and_cycle_fail_closed():
    with pytest.raises(AdmissionError, match="unknown"):
        BoundGraph("sha256:spec", "graph-1", (GraphTask("a", ("missing",)),))
    with pytest.raises(AdmissionError, match="cycle"):
        BoundGraph("sha256:spec", "graph-1", (GraphTask("a", ("b",)), GraphTask("b", ("a",))))


def test_bound_graph_reuses_validated_phase_and_plan_identity():
    root = Path(__file__).resolve().parents[1]
    specification = json.loads(
        (root / "00-GSD-Phases" / "Phase-041-GSD-Master-3.4.0-Execution-Control-P0-Baseline.specification.json").read_text()
    )
    fixture = json.loads(
        (root / "fixtures" / "gsd-execution-control" / "p0" / "phase-plan.json").read_text()
    )
    plan = {**fixture["authoritative_phase"], **fixture["skill_identity"], "tasks": []}
    authoritative = {task["task_id"]: task for task in specification["implementation"]["tasks"]}
    plan["tasks"] = [{**authoritative[item["task_id"]], **item} for item in fixture["tasks"]]
    bound = BoundGraph.from_execution_plan(specification, plan, graph_revision="graph-p041")
    assert bound.phase_id == "P041"
    assert bound.specification_id == "gsd-master-3.4.0-execution-control-p0-baseline"
    assert bound.specification_version == "1.0.0"
    assert bound.plan_digest.startswith("sha256:")
    assert bound.task("P041-T002").predecessors == ("P041-T001",)


def test_bound_graph_rejects_plan_identity_divergence():
    root = Path(__file__).resolve().parents[1]
    specification = json.loads(
        (root / "00-GSD-Phases" / "Phase-041-GSD-Master-3.4.0-Execution-Control-P0-Baseline.specification.json").read_text()
    )
    with pytest.raises(Exception, match="execution plan phase_id"):
        BoundGraph.from_execution_plan(
            specification,
            {"phase_id": "P999"},
            graph_revision="graph-invalid",
        )


def test_admission_is_journal_backed_idempotent_and_replayable(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = JournalStore(path)
    controller = AdmissionController(journal)
    first = controller.admit(
        graph(), states(), task_id="a", attempt_id="attempt-1", operation_id="op-1",
        capacity=2, active_admissions=0,
    )
    second = controller.admit(
        graph(), states(), task_id="a", attempt_id="attempt-1", operation_id="op-1",
        capacity=2, active_admissions=0,
    )
    assert second == first
    assert first.workspace_slot == "slot:a"
    assert controller.replay_admissions() == (first,)
    assert first.workspace_slot_id == "slot:a:attempt-1"
    journal.close()
    reopened = JournalStore(path)
    assert AdmissionController(reopened).replay_admissions() == (first,)
    reopened.close()


def test_admission_rejects_second_task_reservation_and_stale_count(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    controller = AdmissionController(journal)
    controller.admit(
        graph(), states(), task_id="a", attempt_id="attempt-1", operation_id="op-1",
        capacity=2, active_admissions=0,
    )
    with pytest.raises(AdmissionError, match="capacity"):
        controller.admit(
            graph(), states(), task_id="c", attempt_id="attempt-2", operation_id="op-2",
            capacity=1,
        )
    with pytest.raises(AdmissionError, match="count"):
        controller.admit(
            graph(), states(), task_id="c", attempt_id="attempt-2", operation_id="op-2",
            capacity=2, active_admissions=0,
        )
    with pytest.raises(AdmissionError, match="workspace slot"):
        controller.admit(
            graph(), states(), task_id="c", attempt_id="attempt-3", operation_id="op-3",
            capacity=2, workspace_slot="slot:a",
        )
    with pytest.raises(AdmissionError, match="conflicting duplicate"):
        controller.admit(
            graph(), states(), task_id="c", attempt_id="attempt-2", operation_id="op-1",
            capacity=2,
        )
    with pytest.raises(AdmissionError, match="already has"):
        controller.admit(
            graph(), states(), task_id="a", attempt_id="attempt-3", operation_id="op-3",
            capacity=2,
        )
    journal.close()


def test_admission_checks_capacity_workspace_and_authorization_before_commit(tmp_path):
    journal = JournalStore(tmp_path / "journal.sqlite")
    controller = AdmissionController(journal)
    common = dict(graph=graph(), task_states=states(), task_id="a", attempt_id="a1", operation_id="op-1")
    with pytest.raises(AdmissionError, match="capacity"):
        controller.admit(**common, capacity=0, active_admissions=0)
    with pytest.raises(AdmissionError, match="workspace"):
        controller.admit(**common, capacity=1, active_admissions=0, workspace_slot_available=False)
    with pytest.raises(AdmissionError, match="authorization"):
        controller.admit(**common, capacity=1, active_admissions=0, authorization_satisfied=False)
    assert journal.events() == ()
    journal.close()
