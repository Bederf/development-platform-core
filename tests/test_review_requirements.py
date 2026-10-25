import unittest

from adapters.review_requirements import assess_requirements


class ReviewRequirementsTests(unittest.TestCase):
    def test_all_satisfied_requirements_with_resolved_evidence_pass(self):
        decision = assess_requirements(
            [
                {"requirement_ref": "workflow.operator-response", "status": "satisfied", "evidence_refs": ["ui-test"]},
                {"requirement_ref": "workflow.reviewer-disposition", "status": "satisfied", "evidence_refs": ["api-test"]},
            ],
            mandatory_requirement_refs=["workflow.operator-response", "workflow.reviewer-disposition"],
            available_evidence=["ui-test", "api-test"],
            unresolved_blockers=0,
        )
        self.assertTrue(decision.eligible)

    def test_missing_requirement_evidence_blocks(self):
        decision = assess_requirements(
            [{"requirement_ref": "workflow.evidence-display", "status": "satisfied", "evidence_refs": ["missing"]}],
            mandatory_requirement_refs=["workflow.evidence-display"],
            available_evidence=[],
            unresolved_blockers=0,
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.unresolved_refs, ("workflow.evidence-display",))

    def test_unsatisfied_requirement_blocks(self):
        decision = assess_requirements(
            [{"requirement_ref": "workflow.disposition-reason", "status": "open", "evidence_refs": ["test"]}],
            mandatory_requirement_refs=["workflow.disposition-reason"],
            available_evidence=["test"],
            unresolved_blockers=0,
        )
        self.assertFalse(decision.eligible)

    def test_empty_requirements_fail_closed(self):
        decision = assess_requirements([], mandatory_requirement_refs=[], available_evidence=[], unresolved_blockers=0)
        self.assertFalse(decision.eligible)

    def test_omitted_canonical_requirement_blocks(self):
        decision = assess_requirements(
            [{"requirement_ref": "workflow.operator-response", "status": "satisfied", "evidence_refs": ["ui-test"]}],
            mandatory_requirement_refs=["workflow.operator-response", "workflow.evidence-display"],
            available_evidence=["ui-test"],
            unresolved_blockers=0,
        )
        self.assertFalse(decision.eligible)
        self.assertIn("missing:workflow.evidence-display", decision.unresolved_refs)

    def test_unknown_submitted_requirement_blocks(self):
        decision = assess_requirements(
            [{"requirement_ref": "workflow.invented", "status": "satisfied", "evidence_refs": ["test"]}],
            mandatory_requirement_refs=["workflow.operator-response"],
            available_evidence=["test"],
            unresolved_blockers=0,
        )
        self.assertFalse(decision.eligible)
        self.assertIn("unexpected:workflow.invented", decision.unresolved_refs)


if __name__ == "__main__":
    unittest.main()
