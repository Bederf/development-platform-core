import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from capabilities.consumer_conformance import (
    ConsumerEvidence,
    KernelCall,
    KernelConsumptionEvaluator,
    RecordSnapshot,
)


NOW = datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)
SCOPE = {"scope_type": "project", "scope_id": "fixture.consumer"}


def ref(kind, identifier, **extra):
    return {"semantic_type": kind, "id": identifier, "version": "1.0.0", **extra}


class KernelConsumptionConformanceTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = KernelConsumptionEvaluator(
            evaluator_id="core.consumer-evaluator",
            recognized_evidence_issuers={"fixture.harness": {"authority.harness"}},
        )
        self.resolution = {
            "entity_type": "resolution_result",
            "resolution_id": "resolution.fixture",
            "unresolved": [],
        }
        self.candidates = {
            "result_type": "candidate_resolution",
            "eligible_candidates": [ref("implementation", "implementation.a")],
            "unresolved": [],
        }
        self.binding = {
            "entity_type": "capability_binding",
            "binding_id": "binding.fixture",
            "lifecycle_status": "proposed",
        }

    def evidence(self, *, calls=None, inputs=(), presented=None, created=(), snapshots=None, issuer="fixture.harness"):
        calls = calls or (
            KernelCall("resolve_requirements", (self.resolution,)),
            KernelCall("admit_candidates", (self.candidates,)),
        )
        outputs = tuple(item for call in calls for item in call.outputs)
        candidate = ConsumerEvidence(
            evidence_id="evidence.consumer.fixture",
            consumer=ref("implementation", "consumer.radix-init", issuer="fixture.consumer"),
            external_inputs=tuple(inputs),
            kernel_calls=tuple(calls),
            presented_outputs=tuple(outputs if presented is None else presented),
            consumer_created_records=tuple(created),
            snapshots=tuple(
                snapshots
                if snapshots is not None
                else (RecordSnapshot(ref("kernel_record", "record.fixture"), "sha256:same", "sha256:same"),)
            ),
            issuer=issuer,
            authority_binding=ref("authority_binding", "authority.harness"),
            validity_scope=SCOPE,
            observed_at=NOW - timedelta(seconds=1),
        )
        return replace(candidate, digest=candidate.expected_digest())

    def evaluate(self, evidence):
        return self.evaluator.evaluate(evidence, evaluated_at=NOW)

    def test_thin_pass_through_consumer_satisfies_profile(self):
        self.assertEqual(self.evaluate(self.evidence()).outcome, "satisfied")

    def test_rewritten_output_fails(self):
        rewritten = dict(self.resolution, resolution_id="resolution.rewritten")
        result = self.evaluate(self.evidence(presented=(rewritten,)))
        self.assertIn("KERNEL_OUTPUT_REWRITTEN", {item.code for item in result.findings})

    def test_mutated_record_fails(self):
        snapshot = RecordSnapshot(ref("kernel_record", "record.fixture"), "sha256:before", "sha256:after")
        result = self.evaluate(self.evidence(snapshots=(snapshot,)))
        self.assertIn("KERNEL_RECORD_MUTATED", {item.code for item in result.findings})

    def test_unresolved_resolution_blocks_dependent_calls(self):
        unresolved = dict(self.resolution, unresolved=[{"reason": "conflict"}])
        calls = (
            KernelCall("resolve_requirements", (unresolved,)),
            KernelCall("admit_candidates", (self.candidates,)),
        )
        result = self.evaluate(self.evidence(calls=calls))
        self.assertIn("UNRESOLVED_BYPASSED", {item.code for item in result.findings})

    def test_multiple_candidates_require_external_selection(self):
        candidates = dict(self.candidates, eligible_candidates=[ref("implementation", "a"), ref("implementation", "b")])
        calls = (
            KernelCall("resolve_requirements", (self.resolution,)),
            KernelCall("admit_candidates", (candidates,)),
            KernelCall("plan_binding", (self.binding,)),
        )
        policy = ref("policy_decision", "policy.fixture", outcome="ALLOW")
        result = self.evaluate(self.evidence(calls=calls, inputs=(policy,)))
        self.assertIn("SELECTION_INFERRED", {item.code for item in result.findings})

    def test_binding_requires_external_allow_policy(self):
        calls = (
            KernelCall("resolve_requirements", (self.resolution,)),
            KernelCall("admit_candidates", (self.candidates,)),
            KernelCall("plan_binding", (self.binding,)),
        )
        result = self.evaluate(self.evidence(calls=calls))
        self.assertIn("POLICY_INFERRED", {item.code for item in result.findings})

    def test_external_selection_and_policy_allow_proposed_binding(self):
        candidates = dict(self.candidates, eligible_candidates=[ref("implementation", "a"), ref("implementation", "b")])
        calls = (
            KernelCall("resolve_requirements", (self.resolution,)),
            KernelCall("admit_candidates", (candidates,)),
            KernelCall("plan_binding", (self.binding,)),
        )
        selection = {"entity_type": "selection_result", "outcome": "selected"}
        policy = ref("policy_decision", "policy.fixture", outcome="ALLOW")
        self.assertEqual(self.evaluate(self.evidence(calls=calls, inputs=(selection, policy))).outcome, "satisfied")

    def test_consumer_created_decision_record_fails(self):
        created = ({"entity_type": "resolution_result", "resolution_id": "consumer.fake"},)
        result = self.evaluate(self.evidence(created=created))
        self.assertIn("CONSUMER_DECISION_DUPLICATION", {item.code for item in result.findings})

    def test_active_binding_fails(self):
        active = dict(self.binding, lifecycle_status="active")
        calls = (KernelCall("resolve_requirements", (self.resolution,)), KernelCall("plan_binding", (active,)))
        policy = ref("policy_decision", "policy.fixture", outcome="ALLOW")
        result = self.evaluate(self.evidence(calls=calls, inputs=(policy,)))
        self.assertIn("BINDING_ACTIVATED", {item.code for item in result.findings})

    def test_forged_and_self_issued_evidence_fail_closed(self):
        forged = replace(self.evidence(), digest="sha256:forged")
        self.assertIn("EVIDENCE_DIGEST_MISMATCH", {item.code for item in self.evaluate(forged).findings})
        self_issued = self.evidence(issuer="fixture.consumer")
        result = self.evaluate(self_issued)
        self.assertIn("SELF_CERTIFICATION", {item.code for item in result.findings})

    def test_expired_valid_evidence_is_expired_not_satisfied(self):
        evidence = self.evidence()
        evidence = replace(evidence, valid_until=NOW - timedelta(seconds=1), digest="")
        evidence = replace(evidence, digest=evidence.expected_digest())
        self.assertEqual(self.evaluate(evidence).outcome, "expired")


if __name__ == "__main__":
    unittest.main()
