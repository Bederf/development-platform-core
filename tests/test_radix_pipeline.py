import json

import pytest

from adapters.radix.pipeline import (
    PipelineError,
    content_digest,
    create_run,
    record_stage,
    supervisor_decide,
    validate_pipeline_definition,
)


def pipeline_definition():
    roles = [
        {"role_id": "architect", "responsibility": "produce the plan", "input_artifacts": ["objective"], "output_artifacts": ["plan"]},
        {"role_id": "worker", "responsibility": "implement the plan", "input_artifacts": ["plan"], "output_artifacts": ["worker-result"]},
        {"role_id": "validator", "responsibility": "validate the result", "input_artifacts": ["worker-result"], "output_artifacts": ["validation"]},
        {"role_id": "supervisor", "responsibility": "approve evidence", "input_artifacts": ["validation"], "output_artifacts": ["decision"]},
    ]
    authority = lambda stage: {
        "stage_id": stage,
        "authority_ref": "p057-test-authority",
        "decision": "approved",
        "evidence_ref": f"evidence/{stage}",
        "digest": "sha256:" + "a" * 64,
    }
    return {
        "schema": "radix-agent-pipeline.v1",
        "pipeline_id": "test-pipeline",
        "version": "1.0.0",
        "status": "proposed",
        "project_ref": {"project_id": "test-project", "definition_id": "test-definition", "definition_version": "1.0.0", "definition_digest": "sha256:" + "b" * 64},
        "source_ref": {"repository_root": "/tmp/test-project", "revision": "candidate"},
        "roles": roles,
        "stages": [
            {"stage_id": "architect", "role_id": "architect", "depends_on": [], "required_inputs": ["objective"], "outputs": ["plan"], "authorization_required": True, "authorization_ref": authority("architect")},
            {"stage_id": "worker", "role_id": "worker", "depends_on": ["architect"], "required_inputs": ["plan"], "outputs": ["worker-result"], "authorization_required": True, "authorization_ref": authority("worker")},
            {"stage_id": "validator", "role_id": "validator", "depends_on": ["worker"], "required_inputs": ["worker-result"], "outputs": ["validation"], "authorization_required": True, "authorization_ref": authority("validator")},
            {"stage_id": "supervisor", "role_id": "supervisor", "depends_on": ["validator"], "required_inputs": ["validation"], "outputs": ["decision"], "authorization_required": True, "authorization_ref": authority("supervisor")},
        ],
        "approval_gate": {"required_before": "execution", "authority_ref": "p057-test-authority", "merge_allowed": False},
        "evidence_policy": {"run_scoped": True, "content_addressed": True, "failure_is_terminal_or_blocked": True, "verification_authority": "p057-test-authority"},
        "failure_policy": {"timeout_seconds": 60, "heartbeat_interval_seconds": 10, "max_missed_heartbeats": 1, "disconnect_outcome": "blocked", "retry_allowed": False},
    }


def test_pipeline_definition_validates_and_run_is_review_only():
    pipeline = pipeline_definition()
    digest = validate_pipeline_definition(pipeline)
    run = create_run(pipeline, source_revision="abc123", run_id="run-1")
    assert digest == content_digest(pipeline)
    assert run["status"] == "planned"
    assert run["review_only"] is True
    assert run["pipeline_digest"] == digest


def test_pipeline_requires_ordered_artifact_handoffs_and_supervisor_gate():
    pipeline = pipeline_definition()
    run = create_run(pipeline, source_revision="abc123", run_id="run-2")
    with pytest.raises(PipelineError, match="dependency"):
        record_stage(run, pipeline, "worker", artifact={"code": "early"})
    for stage in ("architect", "worker", "validator", "supervisor"):
        record_stage(run, pipeline, stage, artifact={"stage": stage})
    supervisor_decide(run, decision="approved", evidence_ref="evidence/run-2")
    assert run["status"] == "accepted_for_review"


def test_pipeline_rejects_cycles_and_preserves_failure_state():
    pipeline = pipeline_definition()
    pipeline["stages"][0]["depends_on"] = ["supervisor"]
    with pytest.raises(PipelineError, match="cycle"):
        validate_pipeline_definition(pipeline)
