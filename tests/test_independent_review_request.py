import unittest

from tests.test_contracts import validate


class IndependentReviewRequestTests(unittest.TestCase):
    def test_fake_gsd_request_is_versioned_and_bounded(self):
        validate("independent-review-request.v1.schema.json", {
            "schema": "independent-review-request.v1",
            "request_id": "review-request-001",
            "task_ref": "task-001",
            "revision_ref": "revision-001",
            "review_package": "package-001",
            "reviewer_ref": "development-platform-code-reviewer",
            "independence_required": True,
            "evidence_refs": ["spec-001", "diff-001", "tests-001"],
        })

    def test_self_review_request_is_rejected(self):
        with self.assertRaises(Exception):
            validate("independent-review-request.v1.schema.json", {
                "schema": "independent-review-request.v1",
                "request_id": "review-request-002",
                "task_ref": "task-001",
                "revision_ref": "revision-001",
                "review_package": "package-001",
                "reviewer_ref": "coding-agent-same-context",
                "independence_required": False,
                "evidence_refs": ["spec-001"],
            })

    def test_empty_evidence_is_rejected(self):
        with self.assertRaises(Exception):
            validate("independent-review-request.v1.schema.json", {
                "schema": "independent-review-request.v1",
                "request_id": "review-request-003",
                "task_ref": "task-001",
                "revision_ref": "revision-001",
                "review_package": "package-001",
                "reviewer_ref": "development-platform-code-reviewer",
                "independence_required": True,
                "evidence_refs": [],
            })


if __name__ == "__main__":
    unittest.main()
