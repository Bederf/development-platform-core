"""Thin ``radix init`` consumer of governed kernel capabilities."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from capabilities.binding import BindingPlan, PolicyDecisionFact
from capabilities.resolution import CandidateFacts, CandidateResolution, RequirementResolution


class RadixInitError(ValueError):
    """Raised when initialization cannot safely advance."""


class InitKernel(Protocol):
    def resolve_requirements(
        self,
        *,
        requirements: Sequence[Mapping[str, Any]],
        validity_scope: Mapping[str, Any],
        condition_values: Mapping[str, Any],
    ) -> RequirementResolution: ...

    def admit_candidates(
        self,
        *,
        requirement: Mapping[str, Any],
        requirement_resolution: RequirementResolution,
        capability: Mapping[str, Any],
        candidates: Sequence[CandidateFacts],
    ) -> CandidateResolution: ...

    def plan_binding(
        self,
        *,
        binding_id: str,
        requirement: Mapping[str, Any],
        capability: Mapping[str, Any],
        selection_result: Mapping[str, Any],
        selected: CandidateFacts,
        policy_decision: PolicyDecisionFact,
        validity_scope: Mapping[str, Any],
        risk_assessment: Mapping[str, Any] | None,
    ) -> BindingPlan: ...


@dataclass(frozen=True)
class InitAnalysis:
    status: str
    resolution: RequirementResolution
    candidates: Mapping[str, CandidateResolution]
    unresolved: tuple[Mapping[str, Any], ...]
    required_actions: tuple[str, ...]


@dataclass(frozen=True)
class BootstrapPlan:
    schema: str
    project_id: str
    validity_scope: Mapping[str, Any]
    requirement_resolution: Mapping[str, Any]
    proposed_bindings: tuple[Mapping[str, Any], ...]
    generated_artifacts: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RadixInitializer:
    """Coordinate UX state while delegating every decision to the kernel."""

    def __init__(self, kernel: InitKernel) -> None:
        self.kernel = kernel

    def analyze(
        self,
        *,
        requirements: Sequence[Mapping[str, Any]],
        validity_scope: Mapping[str, Any],
        condition_values: Mapping[str, Any],
        capabilities: Mapping[str, Mapping[str, Any]],
        candidates: Mapping[str, Sequence[CandidateFacts]],
    ) -> InitAnalysis:
        resolution = self.kernel.resolve_requirements(
            requirements=requirements,
            validity_scope=validity_scope,
            condition_values=condition_values,
        )
        if resolution.unresolved:
            return InitAnalysis(
                "unresolved",
                resolution,
                {},
                resolution.unresolved,
                ("Resolve requirement conflicts before candidate admission",),
            )

        admitted: dict[str, CandidateResolution] = {}
        unresolved: list[Mapping[str, Any]] = []
        for requirement in resolution.effective_requirements:
            if requirement["strength"] == "prohibited":
                continue
            requirement_id = requirement["requirement_id"]
            capability_id = requirement["capability"]["id"]
            if capability_id not in capabilities:
                unresolved.append(_issue(requirement_id, "capability_definition_missing"))
                continue
            result = self.kernel.admit_candidates(
                requirement=requirement,
                requirement_resolution=resolution,
                capability=capabilities[capability_id],
                candidates=candidates.get(capability_id, ()),
            )
            admitted[requirement_id] = result
            if not result.eligible_candidates:
                unresolved.append(_issue(requirement_id, "no_eligible_candidate"))

        if unresolved:
            return InitAnalysis(
                "unresolved",
                resolution,
                admitted,
                tuple(unresolved),
                ("Supply missing definitions or conformant candidates",),
            )
        return InitAnalysis(
            "selection_required",
            resolution,
            admitted,
            (),
            ("Record an explicit selection for every effective requirement",),
        )

    def build_plan(
        self,
        *,
        project_id: str,
        analysis: InitAnalysis,
        validity_scope: Mapping[str, Any],
        capabilities: Mapping[str, Mapping[str, Any]],
        candidate_facts: Mapping[str, CandidateFacts],
        selections: Mapping[str, Mapping[str, Any]],
        policy_decisions: Mapping[str, PolicyDecisionFact],
    ) -> BootstrapPlan:
        if analysis.status != "selection_required" or analysis.unresolved:
            raise RadixInitError("analysis is unresolved and cannot produce bindings")
        plans: list[BindingPlan] = []
        for requirement in analysis.resolution.effective_requirements:
            if requirement["strength"] == "prohibited":
                continue
            requirement_id = requirement["requirement_id"]
            missing = [
                name
                for name, values in (
                    ("selection", selections),
                    ("candidate facts", candidate_facts),
                    ("policy decision", policy_decisions),
                )
                if requirement_id not in values
            ]
            if missing:
                raise RadixInitError(
                    f"{requirement_id} requires explicit " + ", ".join(missing)
                )
            plan = self.kernel.plan_binding(
                binding_id=f"binding.{project_id}.{requirement_id}",
                requirement=requirement,
                capability=capabilities[requirement["capability"]["id"]],
                selection_result=selections[requirement_id],
                selected=candidate_facts[requirement_id],
                policy_decision=policy_decisions[requirement_id],
                validity_scope=validity_scope,
                risk_assessment=(candidate_facts[requirement_id].risk_assessments or (None,))[0],
            )
            if plan.binding.get("lifecycle_status") != "proposed":
                raise RadixInitError("kernel returned a non-proposed binding")
            plans.append(plan)
        return BootstrapPlan(
            schema="radix-bootstrap-plan.v1-internal",
            project_id=project_id,
            validity_scope=dict(validity_scope),
            requirement_resolution=dict(analysis.resolution.record),
            proposed_bindings=tuple(plan.binding for plan in plans),
            generated_artifacts=("development-platform.yaml", "radix-bootstrap-plan.json"),
            limitations=(
                "Plan generation does not activate, provision, deploy, or execute",
                "Internal plan shape is not a public contract",
            ),
        )

    @staticmethod
    def write_plan(plan: BootstrapPlan, target: Path, *, overwrite: bool = False) -> Path:
        target = target.resolve()
        if target.exists() and not overwrite:
            raise RadixInitError(f"refusing to overwrite existing artifact: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target


def _issue(requirement_id: str, reason: str) -> Mapping[str, Any]:
    return {
        "subject": {
            "semantic_type": "capability_requirement",
            "id": requirement_id,
            "version": "1.0.0",
        },
        "reason_codes": [reason],
    }
