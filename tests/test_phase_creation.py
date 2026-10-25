from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.phase_creation import PhaseCreationError, prepare_phase_creation
from adapters.phase_specification import calculate_specification_hash


def _spec() -> dict:
    value = {
        "schema": "phase-specification.v1",
        "phase": {
            "specification_id": "phase-creation-test",
            "phase_id": "P901",
            "title": "Phase Creation Test",
            "version": "1.0.0",
            "specification_hash": "",
            "created_at": "2026-10-18T00:00:00Z",
            "updated_at": "2026-10-18T00:00:00Z",
            "created_by": "test",
            "provenance": {"source_refs": ["GSD-MASTER-GLOBAL-ONE-SHOT-ORCHESTRATION-POLICY-v1.1"], "supersedes_ref": None},
            "workflow": {"schema": "development-workflow.v1", "workflow_id": None},
        },
        "intent": {"objective": "test", "desired_outcome": "test", "business_context": None},
        "scope": {"in_scope": ["test"], "non_goals": ["production"], "constraints": ["fail closed"]},
        "requirements": [{
            "requirement_id": "P901-R001", "statement": "test", "mandatory": True,
            "acceptance_criteria": [{"criterion_id": "P901-C001", "statement": "test"}],
            "evidence_contract": [{"evidence_type": "test", "required": True, "producer": "test", "verification_method": "test"}],
            "verification_method": "test", "dependencies": [],
        }],
        "implementation": {"tasks": [
            {"task_id": "P901-T002", "statement": "second", "depends_on": ["P901-T001"], "requirement_refs": ["P901-R001"], "expected_artifacts": ["second"]},
            {"task_id": "P901-T001", "statement": "first", "depends_on": [], "requirement_refs": ["P901-R001"], "expected_artifacts": ["first"]},
        ], "execution_strategy": "One admitted phase executes its dependency graph continuously and reaches one review boundary."},
        "verification": {"required_checks": ["focused test"], "required_evidence": ["test"], "forge_required": False, "live_verification_required": False},
        "independent_review": {"required": True, "authority": "development-platform-core.independent-review", "required_context": ["phase"], "required_evidence": ["test"], "remediation_on_findings": "rework"},
        "convergence": {"required": True, "required_conditions": ["separate acceptance decision"], "failure_states": ["REMEDIATION_REQUIRED", "BLOCKED"]},
        "remediation": {"retry_policy": "bounded", "rework_policy": "rework", "escalation_policy": "owner"},
        "acceptance": {"authority": "development-platform-core.acceptance-authority", "workflow_schema": "development-workflow.v1", "required_conditions": ["separate acceptance decision"]},
    }
    value["phase"]["specification_hash"] = calculate_specification_hash(value)
    return value


def test_phase_creation_prepares_one_bound_decision_and_dag(tmp_path: Path) -> None:
    spec_path = tmp_path / "Phase-P901.specification.json"
    markdown_path = tmp_path / "Phase-P901.md"
    preparation_path = tmp_path / "preparation.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    markdown_path.write_text("# P901\nphase_id: P901\n", encoding="utf-8")

    package = prepare_phase_creation(
        specification_path=spec_path,
        markdown_path=markdown_path,
        evidence_path=tmp_path / "run.json",
        preparation_path=preparation_path,
        review_provider_ref="registered-AGY",
    )

    assert package.task_order == ("P901-T001", "P901-T002")
    assert package.review_provider_ref == "registered-AGY"
    assert package.decision_template["action"] == "authorize-phase-execution"
    assert package.prepared_record["authority_granted"] is False
    assert json.loads(preparation_path.read_text())["confirmation_required"] is True


def test_phase_creation_requires_matching_markdown_and_active_policy(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    markdown_path = tmp_path / "phase.md"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    markdown_path.write_text("phase_id: P900\n", encoding="utf-8")
    with pytest.raises(PhaseCreationError, match="does not bind"):
        prepare_phase_creation(specification_path=spec_path, markdown_path=markdown_path, evidence_path=tmp_path / "run.json")

    broken = _spec()
    broken["phase"]["provenance"]["source_refs"] = ["other-policy"]
    broken["phase"]["specification_hash"] = calculate_specification_hash(broken)
    spec_path.write_text(json.dumps(broken), encoding="utf-8")
    markdown_path.write_text("phase_id: P901\n", encoding="utf-8")
    with pytest.raises(PhaseCreationError, match="one-shot policy"):
        prepare_phase_creation(specification_path=spec_path, markdown_path=markdown_path, evidence_path=tmp_path / "run.json")
