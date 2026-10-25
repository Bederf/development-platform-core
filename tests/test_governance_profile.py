import unittest

from adapters.governance_profile import GovernanceProfileError, required_controls, validate_governance_profile


def profile(**overrides):
    value = {
        "schema": "governance-profile.v1",
        "profile_id": "generic-design-001",
        "version": "1.0.0",
        "work_profile": "design",
        "impact_boundaries": ["publication", "runtime_identity"],
        "decisions": [
            {"decision_id": "design-001", "type": "technical_design", "status": "accepted", "authority": "owner", "evidence_refs": ["design"]},
            {"decision_id": "contract-001", "type": "contract_approval", "status": "accepted", "authority": "owner", "evidence_refs": ["review"]},
        ],
        "review": {"required": True, "status": "complete", "retry_limit": 1, "reviewer_ref": "independent-review", "escalation_ref": None},
        "deferrals": [],
        "closeout": {"status": "open", "canonical_summary_ref": None, "superseded_refs": []},
    }
    value.update(overrides)
    return value


class GovernanceProfileTests(unittest.TestCase):
    def test_design_acceptance_does_not_imply_implementation(self):
        validate_governance_profile(profile())
        self.assertNotIn("production_activation_authorization", required_controls(profile()))

    def test_publication_and_runtime_boundaries_escalate_controls(self):
        controls = required_controls(profile())
        self.assertIn("independent_review", controls)
        self.assertIn("explicit_implementation_authorization", controls)
        self.assertIn("rollback_plan", controls)

    def test_production_environment_requires_controls_without_activation(self):
        value = profile(impact_boundaries=["production_environment"])
        controls = required_controls(value)
        self.assertIn("independent_review", controls)
        self.assertIn("explicit_implementation_authorization", controls)
        self.assertIn("rollback_plan", controls)
        self.assertNotIn("production_activation_authorization", controls)

    def test_activation_requires_explicit_authorizations(self):
        value = profile(work_profile="activation")
        with self.assertRaisesRegex(GovernanceProfileError, "activation profile"):
            validate_governance_profile(value)

    def test_authorization_chain_is_ordered(self):
        value = profile(decisions=[profile()["decisions"][0], {"decision_id": "impl-001", "type": "implementation_authorization", "status": "accepted", "authority": "owner", "evidence_refs": ["approval"]}])
        with self.assertRaisesRegex(GovernanceProfileError, "contract approval"):
            validate_governance_profile(value)

    def test_incomplete_review_requires_escalation(self):
        value = profile(review={"required": True, "status": "incomplete_review", "retry_limit": 1, "reviewer_ref": "reviewer", "escalation_ref": None})
        with self.assertRaisesRegex(GovernanceProfileError, "escalation_ref"):
            validate_governance_profile(value)

    def test_closed_profile_requires_canonical_summary(self):
        value = profile(closeout={"status": "closed", "canonical_summary_ref": None, "superseded_refs": []})
        with self.assertRaisesRegex(GovernanceProfileError, "canonical summary"):
            validate_governance_profile(value)

    def test_duplicate_decision_ids_are_rejected(self):
        decisions = profile()["decisions"]
        value = profile(decisions=decisions + [dict(decisions[0])])
        with self.assertRaisesRegex(GovernanceProfileError, "unique"):
            validate_governance_profile(value)

    def test_duplicate_decision_types_are_rejected(self):
        decisions = profile()["decisions"]
        duplicate = dict(decisions[0], decision_id="design-002")
        value = profile(decisions=decisions + [duplicate])
        with self.assertRaisesRegex(GovernanceProfileError, "decision type"):
            validate_governance_profile(value)

    def test_complete_review_requires_reviewer(self):
        value = profile(review={"required": True, "status": "complete", "retry_limit": 1, "reviewer_ref": None, "escalation_ref": None})
        with self.assertRaisesRegex(GovernanceProfileError, "reviewer_ref"):
            validate_governance_profile(value)

    def test_missing_required_decision_field_is_governance_error(self):
        decisions = [dict(profile()["decisions"][0]), profile()["decisions"][1]]
        del decisions[0]["decision_id"]
        value = profile(decisions=decisions)
        with self.assertRaises(GovernanceProfileError):
            validate_governance_profile(value)


if __name__ == "__main__":
    unittest.main()
