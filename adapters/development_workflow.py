"""Provider-neutral development workflow adapter boundary.

This module contains the in-memory fake implementation used for Core
conformance. It emits proposals and reports; it does not authorize gates,
perform repository work, invoke providers, or create acceptance state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker


class DevelopmentWorkflowAdapterError(ValueError):
    """Raised when a workflow proposal cannot satisfy the adapter boundary."""


class DevelopmentWorkflowAdapter(Protocol):
    """Minimal provider-neutral proposal interface."""

    def propose_artifact(self, *, artifact_ref: str, kind: str, stage: str, digest: str, supersedes_ref: str | None = None) -> dict[str, Any]: ...

    def propose_transition(self, *, from_stage: str, to_stage: str, evidence_refs: Sequence[str], decision: str = "ADVANCE") -> dict[str, Any]: ...

    def report_implementation(self, *, artifact_ref: str, task_refs: Sequence[str], digest: str) -> dict[str, Any]: ...

    def report_verification(self, *, artifact_ref: str, verifier_ref: str, outcome: str, evidence_refs: Sequence[str]) -> dict[str, Any]: ...

    def assess_convergence(self, *, artifact_ref: str, requirements_complete: bool, evidence_refs: Sequence[str]) -> dict[str, Any]: ...

    def report_failure(self, *, stage: str, reason: str, evidence_refs: Sequence[str], recoverable: bool) -> dict[str, Any]: ...


class FakeDevelopmentWorkflowAdapter:
    """Deterministic in-memory provider for adapter conformance tests."""

    ALLOWED_KINDS = {"intent", "specification", "assessment", "plan", "task_list", "implementation", "verification", "convergence", "remediation", "acceptance"}
    ALLOWED_STAGES = {"INTENT", "SPECIFICATION", "ASSESSMENT", "PLAN", "TASKS", "IMPLEMENTATION", "VERIFICATION", "CONVERGENCE", "REMEDIATION", "ACCEPTANCE"}

    def __init__(self, *, provider_ref: str = "fake-workflow-provider", clock: Callable[[], str] | None = None) -> None:
        if not provider_ref.strip():
            raise DevelopmentWorkflowAdapterError("provider_ref is required")
        self.provider_ref = provider_ref.strip()
        self.clock = clock or (lambda: datetime.now(UTC).isoformat())
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.transitions: list[dict[str, Any]] = []

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _timestamp(self) -> str:
        return self.clock()

    @staticmethod
    def _validate_fragment(name: str, value: Mapping[str, Any]) -> None:
        schema = json.loads(
            (Path(__file__).parents[1] / "contracts" / "development-workflow.v1.schema.json").read_text(encoding="utf-8")
        )
        fragment = {"$schema": schema["$schema"], "$ref": f"#/$defs/{name}", "$defs": schema["$defs"]}
        Draft202012Validator(fragment, format_checker=FormatChecker()).validate(value)

    @staticmethod
    def _required_strings(values: Sequence[str], name: str) -> list[str]:
        if not values or any(not isinstance(value, str) or not value.strip() for value in values):
            raise DevelopmentWorkflowAdapterError(f"{name} must contain non-empty strings")
        return list(values)

    def propose_artifact(self, *, artifact_ref: str, kind: str, stage: str, digest: str, supersedes_ref: str | None = None) -> dict[str, Any]:
        if not artifact_ref.strip() or kind not in self.ALLOWED_KINDS or stage not in self.ALLOWED_STAGES or not digest.strip():
            raise DevelopmentWorkflowAdapterError("artifact proposal has invalid identity, kind, stage, or digest")
        if artifact_ref in self.artifacts:
            raise DevelopmentWorkflowAdapterError("artifact_ref is immutable and cannot be reused")
        artifact = {
            "artifact_ref": artifact_ref,
            "kind": kind,
            "stage": stage,
            "artifact_version": "1.0.0",
            "digest": digest,
            "producer": self.provider_ref,
            "supersedes_ref": supersedes_ref,
            "created_at": self._timestamp(),
        }
        self._validate_fragment("artifact", artifact)
        self.artifacts[artifact_ref] = artifact
        return {"proposal_type": "artifact", "authority": "provider_proposal", "artifact": dict(artifact)}

    def propose_transition(self, *, from_stage: str, to_stage: str, evidence_refs: Sequence[str], decision: str = "ADVANCE") -> dict[str, Any]:
        if from_stage not in self.ALLOWED_STAGES or to_stage not in self.ALLOWED_STAGES:
            raise DevelopmentWorkflowAdapterError("transition stages are invalid")
        refs = self._required_strings(evidence_refs, "evidence_refs")
        if decision not in {"ADVANCE", "RETURN", "REJECT", "BLOCK", "CANCEL"}:
            raise DevelopmentWorkflowAdapterError("transition decision is invalid")
        transition = {
            "transition_id": f"proposal-transition-{len(self.transitions) + 1}",
            "from_stage": from_stage,
            "to_stage": to_stage,
            "actor": self.provider_ref,
            "decision": decision,
            "evidence_refs": refs,
            "occurred_at": self._timestamp(),
        }
        self._validate_fragment("transition", transition)
        self.transitions.append(transition)
        return {"proposal_type": "transition", "authority": "core_gate_required", "transition": dict(transition)}

    def report_implementation(self, *, artifact_ref: str, task_refs: Sequence[str], digest: str) -> dict[str, Any]:
        refs = self._required_strings(task_refs, "task_refs")
        artifact = self.propose_artifact(artifact_ref=artifact_ref, kind="implementation", stage="IMPLEMENTATION", digest=digest)
        return {"report_type": "implementation", "task_refs": refs, "artifact_proposal": artifact}

    def report_verification(self, *, artifact_ref: str, verifier_ref: str, outcome: str, evidence_refs: Sequence[str]) -> dict[str, Any]:
        if not verifier_ref.strip() or verifier_ref.strip() == self.provider_ref:
            raise DevelopmentWorkflowAdapterError("verification must identify an independent verifier")
        if outcome not in {"PASS", "FAIL", "UNAVAILABLE", "INCOMPLETE"}:
            raise DevelopmentWorkflowAdapterError("verification outcome is invalid")
        refs = self._required_strings(evidence_refs, "evidence_refs")
        artifact = self.propose_artifact(artifact_ref=artifact_ref, kind="verification", stage="VERIFICATION", digest=f"sha256:{artifact_ref}")
        return {"report_type": "verification", "verifier_ref": verifier_ref, "outcome": outcome, "evidence_refs": refs, "artifact_proposal": artifact}

    def assess_convergence(self, *, artifact_ref: str, requirements_complete: bool, evidence_refs: Sequence[str]) -> dict[str, Any]:
        refs = self._required_strings(evidence_refs, "evidence_refs")
        kind = "convergence" if requirements_complete else "remediation"
        stage = "CONVERGENCE" if requirements_complete else "REMEDIATION"
        artifact = self.propose_artifact(artifact_ref=artifact_ref, kind=kind, stage=stage, digest=f"sha256:{artifact_ref}")
        return {"report_type": "convergence", "requirements_complete": requirements_complete, "evidence_refs": refs, "artifact_proposal": artifact}

    def report_failure(self, *, stage: str, reason: str, evidence_refs: Sequence[str], recoverable: bool) -> dict[str, Any]:
        if not reason.strip() or stage not in self.ALLOWED_STAGES:
            raise DevelopmentWorkflowAdapterError("failure report requires a valid stage and reason")
        if not recoverable:
            return {"report_type": "failure", "reason": reason, "recoverable": False, "status": "BLOCKED", "transition_proposal": None}
        transition = self.propose_transition(from_stage=stage, to_stage="REMEDIATION", evidence_refs=evidence_refs, decision="RETURN")
        return {"report_type": "failure", "reason": reason, "recoverable": True, "status": "RETURNED", "transition_proposal": transition}
