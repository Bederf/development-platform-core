"""Conformance for the provider-neutral fake workflow adapter."""

from __future__ import annotations

import unittest

from adapters.development_workflow import DevelopmentWorkflowAdapterError, FakeDevelopmentWorkflowAdapter


class DevelopmentWorkflowAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeDevelopmentWorkflowAdapter()

    def test_artifact_and_transition_proposals_are_schema_shaped(self) -> None:
        artifact = self.adapter.propose_artifact(
            artifact_ref="spec-001", kind="specification", stage="SPECIFICATION", digest="sha256:spec"
        )["artifact"]
        transition = self.adapter.propose_transition(
            from_stage="INTENT", to_stage="SPECIFICATION", evidence_refs=["intent-001"]
        )["transition"]
        self.assertEqual(artifact["producer"], "fake-workflow-provider")
        self.assertEqual(transition["decision"], "ADVANCE")
        self.assertIn("core_gate_required", self.adapter.propose_transition(
            from_stage="SPECIFICATION", to_stage="ASSESSMENT", evidence_refs=["spec-001"]
        )["authority"])

    def test_implementation_and_convergence_reports_remain_proposals(self) -> None:
        implementation = self.adapter.report_implementation(
            artifact_ref="implementation-001", task_refs=["task-001"], digest="sha256:implementation"
        )
        convergence = self.adapter.assess_convergence(
            artifact_ref="convergence-001", requirements_complete=True, evidence_refs=["implementation-001"]
        )
        self.assertEqual(implementation["report_type"], "implementation")
        self.assertEqual(convergence["artifact_proposal"]["authority"], "provider_proposal")
        self.assertNotIn("accept", dir(self.adapter))

    def test_verification_requires_independent_verifier(self) -> None:
        with self.assertRaises(DevelopmentWorkflowAdapterError):
            self.adapter.report_verification(
                artifact_ref="verification-001", verifier_ref="fake-workflow-provider", outcome="PASS", evidence_refs=["tests-001"]
            )
        result = self.adapter.report_verification(
            artifact_ref="verification-001", verifier_ref="independent-verifier", outcome="PASS", evidence_refs=["tests-001"]
        )
        self.assertEqual(result["verifier_ref"], "independent-verifier")
        self.assertEqual(result["artifact_proposal"]["artifact"]["kind"], "verification")

    def test_failed_and_unavailable_paths_are_explicit(self) -> None:
        failed = self.adapter.report_failure(stage="VERIFICATION", reason="failed checks", evidence_refs=["checks-001"], recoverable=False)
        unavailable = self.adapter.report_failure(stage="VERIFICATION", reason="verifier unavailable", evidence_refs=["availability-001"], recoverable=True)
        self.assertEqual(failed["status"], "BLOCKED")
        self.assertIsNone(failed["transition_proposal"])
        self.assertEqual(unavailable["transition_proposal"]["transition"]["decision"], "RETURN")

    def test_invalid_inputs_fail_closed(self) -> None:
        with self.assertRaises(DevelopmentWorkflowAdapterError):
            self.adapter.propose_artifact(artifact_ref="bad", kind="unknown", stage="SPECIFICATION", digest="sha256:x")
        with self.assertRaises(DevelopmentWorkflowAdapterError):
            self.adapter.propose_transition(from_stage="INTENT", to_stage="PLAN", evidence_refs=["e-1"], decision="ALLOW")
        with self.assertRaises(DevelopmentWorkflowAdapterError):
            self.adapter.report_verification(artifact_ref="v-1", verifier_ref="independent", outcome="MAYBE", evidence_refs=["e-1"])
        with self.assertRaises(DevelopmentWorkflowAdapterError):
            self.adapter.report_failure(stage="UNKNOWN", reason="bad stage", evidence_refs=["e-1"], recoverable=True)
        with self.assertRaises(DevelopmentWorkflowAdapterError):
            self.adapter.propose_transition(from_stage="INTENT", to_stage="PLAN", evidence_refs=[""], decision="ADVANCE")

    def test_clock_is_injectable_for_deterministic_evidence(self) -> None:
        adapter = FakeDevelopmentWorkflowAdapter(clock=lambda: "2026-09-08T00:00:00+00:00")
        proposal = adapter.propose_artifact(artifact_ref="spec-clock", kind="specification", stage="SPECIFICATION", digest="sha256:clock")
        self.assertEqual(proposal["artifact"]["created_at"], "2026-09-08T00:00:00+00:00")

    def test_artifact_identity_is_immutable(self) -> None:
        self.adapter.propose_artifact(artifact_ref="spec-001", kind="specification", stage="SPECIFICATION", digest="sha256:one")
        with self.assertRaises(DevelopmentWorkflowAdapterError):
            self.adapter.propose_artifact(artifact_ref="spec-001", kind="specification", stage="SPECIFICATION", digest="sha256:two")
        replacement = self.adapter.propose_artifact(
            artifact_ref="spec-002", kind="specification", stage="SPECIFICATION", digest="sha256:two", supersedes_ref="spec-001"
        )["artifact"]
        self.assertEqual(replacement["supersedes_ref"], "spec-001")


if __name__ == "__main__":
    unittest.main()
