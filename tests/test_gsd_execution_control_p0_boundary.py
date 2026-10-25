"""Executable P0/G0 evidence; intentionally no controller implementation."""

import json
from pathlib import Path

from adapters.phase_specification import validate_execution_plan, validate_phase_specification


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "gsd-execution-control" / "p0"


def _json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_p0_fixture_plan_binds_to_canonical_phase_without_runtime_authority():
    specification = json.loads((ROOT / "00-GSD-Phases" / "Phase-041-GSD-Master-3.4.0-Execution-Control-P0-Baseline.specification.json").read_text())
    fixture = _json("phase-plan.json")
    plan = {**fixture["authoritative_phase"], **fixture["skill_identity"], "tasks": []}
    authoritative = {task["task_id"]: task for task in specification["implementation"]["tasks"]}
    plan["tasks"] = [{**authoritative[task["task_id"]], **task} for task in fixture["tasks"]]
    validate_phase_specification(specification)
    validate_execution_plan(specification, plan)
    assert fixture["fixture_kind"].startswith("test-only-")


def test_controller_state_root_is_distinct_from_legacy_gsd_engine_authority():
    graph = _json("graph.json")
    assert graph["controller_state_root"] != graph["legacy_gsd_engine_root"]
    assert graph["legacy_records_are_controller_authority"] is False
    assert graph["authority"] == "fixture-only"


def test_legacy_run_record_is_observation_not_controller_journal_authority():
    legacy_path = next((ROOT / ".gsd-engine" / "runs").glob("*.json"))
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    controller = {"schema": "test-only-controller-journal.v0", "authority": "fixture-only"}
    assert legacy["schema"].startswith("gsd-master-run")
    assert legacy.get("authority") != "controller-journal"
    assert legacy["schema"] != controller["schema"]


def test_adr030_mapping_is_complete_and_traceable():
    mapping = _json("adr-030-test-map.json")
    assert mapping["status"] == "G0-mapped-not-implemented"
    rules = mapping["rules"]
    assert len(rules) == 21
    assert len({rule["rule_id"] for rule in rules}) == len(rules)
    assert all(rule["source_anchor"] and rule["test_id"] and rule["phase"] for rule in rules)
    assert all(rule["status"] == "planned" for rule in rules)
