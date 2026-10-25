"""Review-only, provider-neutral Radix pipeline controller for P057."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
PIPELINE_SCHEMA = ROOT / "contracts" / "radix-agent-pipeline.v1.candidate.schema.json"


class PipelineError(ValueError):
    """Raised when a review-only pipeline cannot proceed safely."""


def content_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_pipeline_definition(pipeline: Mapping[str, Any]) -> str:
    """Validate the candidate contract and return its content digest."""

    schema = json.loads(PIPELINE_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(pipeline),
        key=lambda error: list(error.path),
    )
    if errors:
        path = ".".join(str(part) for part in errors[0].path) or "root"
        raise PipelineError(f"invalid pipeline definition at {path}: {errors[0].message}")
    roles = {role["role_id"] for role in pipeline["roles"]}
    required_roles = {"architect", "worker", "validator", "supervisor"}
    if roles != required_roles:
        raise PipelineError("pipeline must define exactly architect, worker, validator and supervisor roles")
    stages = {stage["stage_id"]: stage for stage in pipeline["stages"]}
    if len(stages) != len(pipeline["stages"]):
        raise PipelineError("pipeline stage identifiers must be unique")
    for stage in stages.values():
        unknown = set(stage["depends_on"]) - set(stages)
        if unknown:
            raise PipelineError(f"stage {stage['stage_id']} has unknown dependencies: {sorted(unknown)}")
        if stage["authorization_required"] and stage["authorization_ref"]["stage_id"] != stage["stage_id"]:
            raise PipelineError(f"stage authorization does not bind {stage['stage_id']}")
    _assert_acyclic(stages)
    return content_digest(pipeline)


def create_run(pipeline: Mapping[str, Any], *, source_revision: str, run_id: str | None = None) -> dict[str, Any]:
    """Create a planned run; this function never invokes a provider."""

    digest = validate_pipeline_definition(pipeline)
    if not source_revision.strip():
        raise PipelineError("source revision is required")
    return {
        "schema": "radix-pipeline-run.v1",
        "run_id": run_id or f"radix-{uuid.uuid4().hex}",
        "pipeline_id": pipeline["pipeline_id"],
        "pipeline_digest": digest,
        "project_ref": deepcopy(pipeline["project_ref"]),
        "source_ref": {**pipeline["source_ref"], "revision": source_revision},
        "status": "planned",
        "review_only": True,
        "stages": {},
        "supervisor_decision": None,
    }


def record_stage(run: dict[str, Any], pipeline: Mapping[str, Any], stage_id: str, *, artifact: Any) -> dict[str, Any]:
    """Record an artifact for a stage after dependency and authorization checks."""

    validate_pipeline_definition(pipeline)
    if run.get("status") in {"blocked", "failed", "completed"}:
        raise PipelineError(f"run is terminal: {run.get('status')}")
    stage = next((item for item in pipeline["stages"] if item["stage_id"] == stage_id), None)
    if stage is None:
        raise PipelineError(f"unknown pipeline stage: {stage_id}")
    recorded = run["stages"]
    for dependency in stage["depends_on"]:
        if recorded.get(dependency, {}).get("status") != "completed":
            raise PipelineError(f"stage dependency is incomplete: {dependency}")
    if stage["authorization_required"] and stage["authorization_ref"]["decision"] != "approved":
        raise PipelineError(f"stage authorization is not approved: {stage_id}")
    artifact_copy = deepcopy(artifact)
    recorded[stage_id] = {
        "role_id": stage["role_id"],
        "status": "completed",
        "artifact": artifact_copy,
        "artifact_digest": content_digest(artifact_copy),
    }
    run["status"] = "review_only_ready" if stage_id == "supervisor" else "in_progress"
    return run


def record_failure(run: dict[str, Any], *, stage_id: str, reason: str, outcome: str = "blocked") -> dict[str, Any]:
    if outcome not in {"blocked", "failed"}:
        raise PipelineError("failure outcome must be blocked or failed")
    if not reason.strip():
        raise PipelineError("failure reason is required")
    run["status"] = outcome
    run["failure"] = {"stage_id": stage_id, "reason": reason}
    return run


def supervisor_decide(run: dict[str, Any], *, decision: str, evidence_ref: str) -> dict[str, Any]:
    if decision not in {"approved", "rejected"}:
        raise PipelineError("supervisor decision must be approved or rejected")
    if not evidence_ref.strip():
        raise PipelineError("supervisor evidence reference is required")
    if run.get("status") != "review_only_ready":
        raise PipelineError("supervisor decision requires a completed review-only pipeline")
    run["supervisor_decision"] = {"decision": decision, "evidence_ref": evidence_ref}
    run["status"] = "accepted_for_review" if decision == "approved" else "blocked"
    return run


def _assert_acyclic(stages: Mapping[str, Mapping[str, Any]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_id: str) -> None:
        if stage_id in visiting:
            raise PipelineError("pipeline stages contain a cycle")
        if stage_id in visited:
            return
        visiting.add(stage_id)
        for dependency in stages[stage_id]["depends_on"]:
            visit(dependency)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id in stages:
        visit(stage_id)
