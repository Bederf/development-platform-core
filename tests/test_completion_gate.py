import unittest

from adapters.completion_gate import assess_completion


PASSED_CYCLE = {
    "outcome": "PASS",
    "next_action": "forge_verify",
    "status": "PASSED",
    "review_result_ref": "review:revision-001",
}

PASSED_REVIEW = {
    "schema": "code-review-result.v1",
    "review_id": "review:revision-001",
    "attempt_ref": "revision-001",
    "independence": "independent",
    "classification": {},
    "providers": {"considered": ["gemini"], "selected": ["gemini"], "skipped": []},
    "findings": [],
    "disposition": "PASS",
    "evidence": [
        {"kind": "specification", "ref": "spec-001"},
        {"kind": "diff", "ref": "diff-001"},
        {"kind": "verification", "ref": "tests-001"},
    ],
    "generated_at": "2026-09-06T00:00:00Z",
}


class CompletionGateTests(unittest.TestCase):
    def test_completion_requires_all_independent_prerequisites(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="PASSED",
        )
        self.assertTrue(decision.eligible)

    def test_reviewer_pass_alone_is_not_completion(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=False,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="NOT_RUN",
        )
        self.assertFalse(decision.eligible)

    def test_non_blocking_advisories_can_proceed_to_forge(self):
        cycle = {**PASSED_CYCLE, "outcome": "PASS_WITH_ADVISORIES"}
        decision = assess_completion(
            cycle,
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="PASSED",
        )
        self.assertTrue(decision.eligible)

    def test_unresolved_blocker_blocks_completion(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=1,
            forge_status="PASSED",
        )
        self.assertFalse(decision.eligible)

    def test_failed_forge_blocks_completion(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="FAILED",
        )
        self.assertFalse(decision.eligible)

    def test_non_forge_phase_accepts_explicit_not_required_status(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="NOT_REQUIRED",
            forge_required=False,
        )
        self.assertTrue(decision.eligible)

    def test_non_forge_phase_rejects_failed_forge_status(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="FAILED",
            forge_required=False,
        )
        self.assertFalse(decision.eligible)

    def test_non_pass_review_cannot_complete(self):
        decision = assess_completion(
            {"outcome": "CHANGES_REQUIRED", "next_action": "implement_fix", "status": "OPEN"},
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="PASSED",
        )
        self.assertFalse(decision.eligible)

    def test_invalid_blocker_count_fails_closed(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=True,
            forge_status="PASSED",
        )
        self.assertFalse(decision.eligible)

    def test_unsatisfied_requirements_block_completion(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=False,
            independent_review_result=PASSED_REVIEW,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="PASSED",
        )
        self.assertFalse(decision.eligible)

    def test_evidence_aggregator_cannot_satisfy_independent_review(self):
        review = {**PASSED_REVIEW, "providers": {
            "considered": ["evidence_reviewer"],
            "selected": ["evidence_reviewer"],
            "skipped": [],
        }}
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=review,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="PASSED",
        )
        self.assertFalse(decision.eligible)
        self.assertIn("evidence aggregation", decision.reason)

    def test_missing_review_result_cannot_be_asserted_by_boolean(self):
        decision = assess_completion(
            PASSED_CYCLE,
            requirements_satisfied=True,
            independent_review_result=None,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="PASSED",
        )
        self.assertFalse(decision.eligible)

    def test_low_risk_completion_does_not_require_independent_review(self):
        cycle = {**PASSED_CYCLE, "next_action": "complete"}
        decision = assess_completion(
            cycle,
            requirements_satisfied=True,
            independent_review_result=None,
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="NOT_REQUIRED",
            forge_required=False,
            independent_review_required=False,
        )
        self.assertTrue(decision.eligible)


if __name__ == "__main__":
    unittest.main()
