import unittest

from adapters.review_loop import ReviewLoopPolicyError, plan_next_action


def cycle(**overrides):
    value = {
        "cycle_number": 1,
        "max_cycles": 3,
        "outcome": "CHANGES_REQUIRED",
        "next_action": "implement_fix",
        "status": "OPEN",
        "finding_refs": ["finding-001"],
    }
    value.update(overrides)
    return value


class ReviewLoopPolicyTests(unittest.TestCase):
    def test_changes_required_returns_to_implementation(self):
        decision = plan_next_action(cycle())
        self.assertEqual(decision.action, "implement_fix")
        self.assertTrue(decision.requires_new_revision)
        self.assertFalse(decision.terminal)

    def test_pass_routes_to_forge_but_is_not_completion(self):
        decision = plan_next_action(cycle(
            outcome="PASS", next_action="forge_verify", status="PASSED", finding_refs=[]
        ))
        self.assertEqual(decision.action, "forge_verify")
        self.assertFalse(decision.terminal)

    def test_low_risk_pass_completes_without_independent_review(self):
        decision = plan_next_action(cycle(
            outcome="PASS",
            next_action="complete",
            status="PASSED",
            finding_refs=[],
            independent_review_required=False,
        ))
        self.assertEqual(decision.action, "complete")
        self.assertTrue(decision.terminal)

    def test_third_failed_cycle_is_terminal(self):
        decision = plan_next_action(cycle(
            cycle_number=3, next_action="escalate", status="ESCALATED"
        ))
        self.assertTrue(decision.terminal)
        self.assertFalse(decision.requires_new_revision)

    def test_blocked_review_cannot_route_to_forge(self):
        with self.assertRaises(ReviewLoopPolicyError):
            plan_next_action(cycle(
                outcome="BLOCKED", next_action="forge_verify", status="OPEN"
            ))

    def test_invalid_cycle_bound_is_rejected(self):
        with self.assertRaises(ReviewLoopPolicyError):
            plan_next_action(cycle(max_cycles=4))


if __name__ == "__main__":
    unittest.main()
