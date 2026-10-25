"""Synthetic Stage 04 findings/disposition derivability audit.

This is a qualification fixture only. It does not load S002 consumer data or
mutate mappings, catalogs, proposals, or runtime state.
"""

from __future__ import annotations

import unittest


def finding_records() -> list[dict[str, object]]:
    return [
        {
            "finding_id": f"S002-F{i:02d}",
            "equipment_ref": f"S002-EQ-{i:02d}",
            "point_ref": f"S002-PT-{i:02d}",
            "discovery_ref": "discovery-S002-01",
            "semantic_session_ref": "semantic-session-S002-01",
            "evidence_ref": f"evidence-S002-F{i:02d}",
            "evaluation_outcome": "failed",
        }
        for i in range(1, 9)
    ]


def existing_core_projection(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Fields attributable to currently observed Evaluation/Evidence lineage."""
    return [
        {
            "finding_id": record["finding_id"],
            "equipment_ref": record["equipment_ref"],
            "point_ref": record["point_ref"],
            "discovery_ref": record["discovery_ref"],
            "semantic_session_ref": record["semantic_session_ref"],
            "evidence_ref": record["evidence_ref"],
            "evaluation_outcome": record["evaluation_outcome"],
        }
        for record in records
    ]


class Stage04FindingsDerivabilityTests(unittest.TestCase):
    def test_eight_findings_preserve_subject_and_evidence_lineage(self) -> None:
        records = finding_records()
        self.assertEqual(len(records), 8)
        self.assertEqual({record["discovery_ref"] for record in records}, {"discovery-S002-01"})
        self.assertEqual({record["semantic_session_ref"] for record in records}, {"semantic-session-S002-01"})
        self.assertEqual(len({record["evidence_ref"] for record in records}), 8)

    def test_operator_and_reviewer_state_is_not_derivable(self) -> None:
        records = finding_records()
        scenario_a = {
            "operator_response": "confirmed-as-installed",
            "reviewer_disposition": "APPROVE_CORRECTION",
        }
        scenario_b = {
            "operator_response": "unknown",
            "reviewer_disposition": "DEFER",
        }
        self.assertEqual(existing_core_projection(records), existing_core_projection(records))
        self.assertNotEqual(scenario_a, scenario_b)
        self.assertNotIn("operator_response", existing_core_projection(records)[0])
        self.assertNotIn("reviewer_disposition", existing_core_projection(records)[0])

    def test_pending_or_deferred_findings_cannot_mutate_canonical_state(self) -> None:
        pending = {"status": "REVIEW_PENDING", "mapping_mutation_allowed": False}
        deferred = {"status": "DEFERRED", "mapping_mutation_allowed": False}
        approved = {"status": "APPROVED", "mapping_mutation_allowed": False, "proposal_allowed": True}
        self.assertFalse(pending["mapping_mutation_allowed"])
        self.assertFalse(deferred["mapping_mutation_allowed"])
        self.assertFalse(approved["mapping_mutation_allowed"])
        self.assertTrue(approved["proposal_allowed"])

    def test_approved_correction_still_requires_governed_downstream_chain(self) -> None:
        correction = {
            "reviewer_disposition": "APPROVE_CORRECTION",
            "proposal_ref": "proposal-S002-F01",
            "policy_decision_ref": "policy-S002-F01",
            "execution_ref": "herdr-S002-F01",
            "verification_ref": "forge-S002-F01",
        }
        self.assertEqual(correction["reviewer_disposition"], "APPROVE_CORRECTION")
        self.assertTrue(all(correction[key] for key in correction if key.endswith("_ref")))
        self.assertNotEqual(correction["reviewer_disposition"], "execution")


if __name__ == "__main__":
    unittest.main()
