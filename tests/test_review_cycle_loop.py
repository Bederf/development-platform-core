import unittest

from adapters.code_review import FakeCodeReviewAgent
from adapters.code_review_context import build_review_package
from adapters.review_cycle import FakeReviewCycleCoordinator


def package(attempt_ref):
    return build_review_package(
        attempt_ref=attempt_ref,
        specification="Implement the bounded review workflow.",
        diff=f"diff for {attempt_ref}",
        changed_files=["implementation.py"],
        tests=[{"name": "focused", "status": "passed"}],
    )


class ReviewCycleLoopTests(unittest.TestCase):
    def test_changes_required_then_pass_preserves_finding_and_reaches_forge(self):
        finding = {
            "id": "missing-focused-test",
            "severity": "major",
            "confidence": "high",
            "title": "Focused test is missing",
            "description": "The workflow lacks a focused test.",
            "category": "verification",
            "evidence_ref": "diff-001",
            "recommendation": "Add the focused test.",
            "source": "fake-fixture",
        }

        class TwoRevisionReviewer:
            def __init__(self):
                self.calls = 0

            def review(self, review_package):
                self.calls += 1
                if self.calls == 1:
                    return FakeCodeReviewAgent().review(
                        {"attempt_ref": review_package.attempt_ref, "independence": "independent"},
                        findings=[finding],
                        evidence=[{"kind": "specification", "ref": "spec-001"}, {"kind": "diff", "ref": "diff-001"}, {"kind": "tests", "ref": "tests-001"}],
                    )
                return FakeCodeReviewAgent().review(
                    {"attempt_ref": review_package.attempt_ref, "independence": "independent"},
                    evidence=[{"kind": "specification", "ref": "spec-001"}, {"kind": "diff", "ref": "diff-002"}, {"kind": "tests", "ref": "tests-002"}],
                )

        coordinator = FakeReviewCycleCoordinator(TwoRevisionReviewer())
        first = coordinator.run_cycle(package("revision-001"), task_ref="task-001", cycle_number=1)
        second = coordinator.run_cycle(package("revision-002"), task_ref="task-001", cycle_number=2, prior_cycle_ref=first["cycle_id"])

        self.assertEqual(first["outcome"], "CHANGES_REQUIRED")
        self.assertEqual(first["next_action"], "implement_fix")
        self.assertEqual(second["outcome"], "PASS")
        self.assertEqual(second["next_action"], "forge_verify")
        self.assertEqual(first["finding_refs"], ["missing-focused-test"])
        self.assertNotIn("complete", second)

    def test_three_failed_reviews_escalate_without_fourth_revision(self):
        finding = {
            "id": "persistent-blocker",
            "severity": "blocker",
            "confidence": "very_high",
            "title": "Persistent blocker",
            "description": "The blocker remains unresolved.",
            "category": "correctness",
            "evidence_ref": "diff-001",
            "recommendation": "Resolve the blocker.",
            "source": "fake-fixture",
        }
        reviewer = FakeCodeReviewAgent()
        # The fake reviewer is supplied the finding through a wrapper so every
        # revision remains independently reviewable and produces the same finding.
        class PersistentReviewer:
            def review(self, review_package):
                return reviewer.review(
                    {"attempt_ref": review_package.attempt_ref, "independence": "independent"},
                    findings=[finding],
                    evidence=[{"kind": "specification", "ref": "spec-002"}, {"kind": "diff", "ref": "diff-002"}, {"kind": "tests", "ref": "tests-002"}],
                )

        coordinator = FakeReviewCycleCoordinator(PersistentReviewer())
        first = coordinator.run_cycle(package("revision-001"), task_ref="task-002", cycle_number=1)
        second = coordinator.run_cycle(package("revision-002"), task_ref="task-002", cycle_number=2, prior_cycle_ref=first["cycle_id"])
        third = coordinator.run_cycle(package("revision-003"), task_ref="task-002", cycle_number=3, prior_cycle_ref=second["cycle_id"])

        self.assertEqual(third["status"], "ESCALATED")
        self.assertEqual(third["next_action"], "escalate")
        self.assertIsNone(third["next_revision_ref"])
        self.assertEqual(first["finding_refs"], second["finding_refs"])
        self.assertEqual(second["finding_refs"], third["finding_refs"])


if __name__ == "__main__":
    unittest.main()
