import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from adapters.radix.initializer import RadixInitError, RadixInitializer
from capabilities.binding import BindingPlan
from capabilities.consumer_conformance import (
    ConsumerEvidence,
    KernelCall,
    KernelConsumptionEvaluator,
    RecordSnapshot,
)
from capabilities.resolution import (
    CandidateResolution,
    PolicyInputPackage,
    RequirementResolution,
)


SCOPE = {"scope_type": "project", "scope_id": "fixture.init"}
REQUIREMENT = {
    "requirement_id": "requirement.compile",
    "strength": "required",
    "capability": {"semantic_type": "capability", "id": "compile", "version": "1.0.0"},
}
CAPABILITY = {"capability_id": "compile", "version": "1.0.0"}


def resolution(unresolved=()):
    return RequirementResolution(
        effective_requirements=(REQUIREMENT,),
        rejected_requirements=(),
        findings=(),
        unresolved=tuple(unresolved),
        record={"entity_type": "resolution_result", "resolution_id": "resolution.init", "unresolved": list(unresolved)},
    )


def candidates(eligible=True):
    refs = ({"semantic_type": "implementation", "id": "compiler", "version": "1.0.0"},) if eligible else ()
    policy = PolicyInputPackage(
        requirement={"semantic_type": "capability_requirement", "id": "requirement.compile", "version": "1.0.0"},
        resolution={"semantic_type": "resolution_result", "id": "resolution.init", "version": "1.0.0"},
        eligible_candidates=refs,
        rejected_candidates=(),
        conformance_claims=(),
        compatibility_assessments=(),
        constraint_assessments=(),
        risk_assessments=(),
        unresolved=(),
        limitations=(),
    )
    return CandidateResolution(refs, (), (), policy)


class RadixInitializerTests(unittest.TestCase):
    def setUp(self):
        self.kernel = Mock()
        self.kernel.resolve_requirements.return_value = resolution()
        self.kernel.admit_candidates.return_value = candidates()
        self.initializer = RadixInitializer(self.kernel)

    def analyze(self):
        return self.initializer.analyze(
            requirements=(REQUIREMENT,),
            validity_scope=SCOPE,
            condition_values={},
            capabilities={"compile": CAPABILITY},
            candidates={"compile": ()},
        )

    def test_analyze_delegates_resolution_and_admission_to_kernel(self):
        result = self.analyze()
        self.assertEqual(result.status, "selection_required")
        self.kernel.resolve_requirements.assert_called_once()
        self.kernel.admit_candidates.assert_called_once()
        self.assertNotIn("selected_candidate", result.__dict__)

    def test_unresolved_resolution_stops_before_candidate_admission(self):
        issue = {"subject": {"id": "compile"}, "reason_codes": ["conflict"]}
        self.kernel.resolve_requirements.return_value = resolution((issue,))
        result = self.analyze()
        self.assertEqual(result.status, "unresolved")
        self.kernel.admit_candidates.assert_not_called()

    def test_missing_capability_or_candidate_remains_visible(self):
        missing_definition = self.initializer.analyze(
            requirements=(REQUIREMENT,), validity_scope=SCOPE, condition_values={}, capabilities={}, candidates={}
        )
        self.assertEqual(missing_definition.status, "unresolved")
        self.kernel.admit_candidates.assert_not_called()

        self.kernel.reset_mock()
        self.kernel.resolve_requirements.return_value = resolution()
        self.kernel.admit_candidates.return_value = candidates(False)
        no_candidate = self.analyze()
        self.assertEqual(no_candidate.status, "unresolved")

    def test_build_plan_requires_external_selection_candidate_and_policy(self):
        with self.assertRaisesRegex(RadixInitError, "explicit selection"):
            self.initializer.build_plan(
                project_id="fixture",
                analysis=self.analyze(),
                validity_scope=SCOPE,
                capabilities={"compile": CAPABILITY},
                candidate_facts={},
                selections={},
                policy_decisions={},
            )
        self.kernel.plan_binding.assert_not_called()

    def test_build_plan_accepts_only_kernel_proposed_binding(self):
        proposed = {"entity_type": "capability_binding", "binding_id": "binding.fixture", "lifecycle_status": "proposed"}
        self.kernel.plan_binding.return_value = BindingPlan(proposed, (), {"semantic_type": "policy_decision"}, ())
        facts = Mock(risk_assessments=())
        plan = self.initializer.build_plan(
            project_id="fixture",
            analysis=self.analyze(),
            validity_scope=SCOPE,
            capabilities={"compile": CAPABILITY},
            candidate_facts={"requirement.compile": facts},
            selections={"requirement.compile": {"entity_type": "selection_result"}},
            policy_decisions={"requirement.compile": Mock()},
        )
        self.assertEqual(plan.proposed_bindings, (proposed,))
        self.kernel.plan_binding.assert_called_once()

        self.kernel.plan_binding.return_value = BindingPlan(dict(proposed, lifecycle_status="active"), (), {}, ())
        with self.assertRaisesRegex(RadixInitError, "non-proposed"):
            self.initializer.build_plan(
                project_id="fixture",
                analysis=self.analyze(),
                validity_scope=SCOPE,
                capabilities={"compile": CAPABILITY},
                candidate_facts={"requirement.compile": facts},
                selections={"requirement.compile": {}},
                policy_decisions={"requirement.compile": Mock()},
            )

    def test_plan_writer_is_deterministic_and_refuses_overwrite(self):
        proposed = {"entity_type": "capability_binding", "binding_id": "binding.fixture", "lifecycle_status": "proposed"}
        self.kernel.plan_binding.return_value = BindingPlan(proposed, (), {}, ())
        plan = self.initializer.build_plan(
            project_id="fixture",
            analysis=self.analyze(),
            validity_scope=SCOPE,
            capabilities={"compile": CAPABILITY},
            candidate_facts={"requirement.compile": Mock(risk_assessments=())},
            selections={"requirement.compile": {}},
            policy_decisions={"requirement.compile": Mock()},
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "radix-bootstrap-plan.json"
            self.initializer.write_plan(plan, target)
            self.assertEqual(json.loads(target.read_text())["project_id"], "fixture")
            with self.assertRaisesRegex(RadixInitError, "overwrite"):
                self.initializer.write_plan(plan, target)

    def test_initializer_behavior_passes_kernel_consumption_profile(self):
        analysis = self.analyze()
        evidence = ConsumerEvidence(
            evidence_id="evidence.radix-init.fixture",
            consumer={"semantic_type": "implementation", "id": "radix.init", "version": "0.1.0", "issuer": "core.radix"},
            external_inputs=(),
            kernel_calls=(
                KernelCall("resolve_requirements", (analysis.resolution.record,)),
                KernelCall(
                    "admit_candidates",
                    ({"result_type": "candidate_resolution", "eligible_candidates": list(analysis.candidates["requirement.compile"].eligible_candidates)},),
                ),
            ),
            presented_outputs=(analysis.resolution.record,),
            consumer_created_records=(),
            snapshots=(RecordSnapshot({"semantic_type": "kernel_record", "id": "resolution.init", "version": "1.0.0"}, "sha256:same", "sha256:same"),),
            issuer="fixture.independent-harness",
            authority_binding={"semantic_type": "authority_binding", "id": "authority.harness", "version": "1.0.0"},
            validity_scope=SCOPE,
            observed_at=datetime(2026, 8, 25, 15, 59, tzinfo=timezone.utc),
        )
        evidence = replace(evidence, digest=evidence.expected_digest())
        evaluator = KernelConsumptionEvaluator(
            evaluator_id="core.consumer-evaluator",
            recognized_evidence_issuers={"fixture.independent-harness": {"authority.harness"}},
        )
        result = evaluator.evaluate(
            evidence, evaluated_at=datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(result.outcome, "satisfied")


if __name__ == "__main__":
    unittest.main()
