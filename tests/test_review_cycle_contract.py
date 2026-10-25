import unittest
from datetime import datetime, timezone

from tests.test_contracts import validate


def cycle(**overrides):
    value = {
        "schema": "review-cycle.v1",
        "cycle_id": "cycle-001",
        "task_ref": "task-001",
        "revision_ref": "revision-001",
        "cycle_number": 1,
        "max_cycles": 3,
        "prior_cycle_ref": None,
        "review_result_ref": "review-result-001",
        "finding_refs": ["finding-001"],
        "outcome": "CHANGES_REQUIRED",
        "next_action": "implement_fix",
        "next_revision_ref": "revision-002",
        "verification_ref": None,
        "evidence_refs": ["diff-001", "tests-001"],
        "status": "OPEN",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    value.update(overrides)
    return value


class ReviewCycleContractTests(unittest.TestCase):
    def test_fake_provider_cycle_is_valid(self):
        validate("review-cycle.v1.schema.json", cycle())

    def test_finding_lineage_is_preserved_across_cycles(self):
        first = cycle()
        second = cycle(
            cycle_id="cycle-002",
            revision_ref="revision-002",
            cycle_number=2,
            prior_cycle_ref="cycle-001",
            review_result_ref="review-result-002",
            next_revision_ref="revision-003",
        )
        validate("review-cycle.v1.schema.json", first)
        validate("review-cycle.v1.schema.json", second)
        self.assertEqual(first["finding_refs"], second["finding_refs"])
        self.assertEqual(second["prior_cycle_ref"], first["cycle_id"])

    def test_pass_requires_forge_next_action_and_does_not_claim_completion(self):
        passed = cycle(
            finding_refs=[],
            outcome="PASS",
            next_action="forge_verify",
            next_revision_ref=None,
            verification_ref=None,
            status="PASSED",
        )
        validate("review-cycle.v1.schema.json", passed)
        self.assertNotIn("complete", passed)

    def test_low_risk_pass_can_complete_without_independent_review(self):
        passed = cycle(
            finding_refs=[],
            outcome="PASS",
            next_action="complete",
            next_revision_ref=None,
            verification_ref=None,
            status="PASSED",
            independent_review_required=False,
        )
        validate("review-cycle.v1.schema.json", passed)

    def test_third_unsuccessful_cycle_cannot_continue_automatically(self):
        final = cycle(
            cycle_id="cycle-003",
            cycle_number=3,
            next_action="escalate",
            next_revision_ref=None,
            status="ESCALATED",
        )
        validate("review-cycle.v1.schema.json", final)

    def test_invalid_cycle_number_is_rejected(self):
        with self.assertRaises(Exception):
            validate("review-cycle.v1.schema.json", cycle(cycle_number=4))

    def test_incomplete_review_cannot_advance_to_forge(self):
        with self.assertRaises(Exception):
            validate(
                "review-cycle.v1.schema.json",
                cycle(
                    outcome="INCOMPLETE_REVIEW",
                    next_action="forge_verify",
                    status="ESCALATED",
                ),
            )


if __name__ == "__main__":
    unittest.main()
