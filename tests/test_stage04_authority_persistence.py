"""Disposable authority/persistence fixture for Stage 04 findings."""

from __future__ import annotations

import unittest


class GovernanceError(ValueError):
    pass


class DisposableFindingStore:
    def __init__(self) -> None:
        self.reviews: dict[str, list[dict[str, object]]] = {}
        self.canonical_mappings: dict[str, str] = {}
        self.authorized_reviewers = {"reviewer-1"}

    def persist_review(self, record: dict[str, object]) -> None:
        self.reviews.setdefault(str(record["finding_id"]), []).append(dict(record))

    def approve_proposal(self, finding_id: str, reviewer: str) -> str:
        history = self.reviews[finding_id]
        current = history[-1]
        if current["status"] != "APPROVED" or reviewer not in self.authorized_reviewers:
            raise GovernanceError("approval unavailable")
        return f"proposal:{finding_id}:revision:{current['revision']}"

    def mutate_canonical(self, finding_id: str, proposal_ref: str) -> None:
        raise GovernanceError("canonical mutation requires separate governed consumer authority")


class Stage04AuthorityPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = DisposableFindingStore()

    def test_all_eight_findings_persist_with_lineage(self) -> None:
        for index in range(1, 9):
            self.store.persist_review(
                {
                    "finding_id": f"S002-F{index:02d}",
                    "revision": 1,
                    "status": "REVIEW_PENDING",
                    "discovery_ref": "discovery-S002-01",
                    "semantic_session_ref": "semantic-session-S002-01",
                    "evidence_ref": f"evidence-S002-F{index:02d}",
                }
            )
        self.assertEqual(len(self.store.reviews), 8)
        self.assertTrue(all(len(history) == 1 for history in self.store.reviews.values()))
        self.assertTrue(all(record["status"] == "REVIEW_PENDING" for history in self.store.reviews.values() for record in history))

    def test_pending_and_deferred_findings_cannot_create_proposals(self) -> None:
        self.store.persist_review({"finding_id": "S002-F01", "revision": 1, "status": "REVIEW_PENDING"})
        self.store.persist_review({"finding_id": "S002-F02", "revision": 1, "status": "DEFERRED"})
        for finding_id in ("S002-F01", "S002-F02"):
            with self.subTest(finding_id=finding_id), self.assertRaises(GovernanceError):
                self.store.approve_proposal(finding_id, "reviewer-1")

    def test_approval_requires_authorized_reviewer_and_preserves_revision(self) -> None:
        self.store.persist_review({"finding_id": "S002-F03", "revision": 1, "status": "REVIEW_PENDING"})
        self.store.persist_review({"finding_id": "S002-F03", "revision": 2, "status": "APPROVED"})
        with self.assertRaises(GovernanceError):
            self.store.approve_proposal("S002-F03", "operator-1")
        self.assertEqual(self.store.approve_proposal("S002-F03", "reviewer-1"), "proposal:S002-F03:revision:2")
        self.assertEqual([record["revision"] for record in self.store.reviews["S002-F03"]], [1, 2])

    def test_canonical_mutation_remains_outside_candidate_authority(self) -> None:
        self.store.persist_review({"finding_id": "S002-F04", "revision": 1, "status": "APPROVED"})
        proposal = self.store.approve_proposal("S002-F04", "reviewer-1")
        with self.assertRaises(GovernanceError):
            self.store.mutate_canonical("S002-F04", proposal)
        self.assertEqual(self.store.canonical_mappings, {})

    def test_scope_and_downstream_lineage_are_explicit(self) -> None:
        record = {
            "finding_id": "S002-F05",
            "revision": 1,
            "status": "APPROVED",
            "scope": "S002",
            "proposal_ref": "proposal:S002-F05:revision:1",
            "policy_decision_ref": "policy:S002-F05",
            "execution_ref": "herdr:S002-F05",
            "verification_ref": "forge:S002-F05",
        }
        self.assertEqual(record["scope"], "S002")
        self.assertEqual(record["proposal_ref"].split(":")[-1], "1")
        self.assertTrue(all(record[key].startswith(prefix) for key, prefix in (("policy_decision_ref", "policy:"), ("execution_ref", "herdr:"), ("verification_ref", "forge:"))))


if __name__ == "__main__":
    unittest.main()
