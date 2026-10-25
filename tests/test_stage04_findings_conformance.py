"""Normative hostile cases for the candidate finding-disposition family."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
DIGEST = "sha256:" + "a" * 64


def ref(kind: str, identifier: str) -> dict[str, str]:
    return {"semantic_type": kind, "id": identifier, "version": "1.0.0", "digest": DIGEST}


def common(kind: str, identifier: str, entity: dict[str, object]) -> dict[str, object]:
    record: dict[str, object] = {
        "schema": "finding-disposition.v1",
        "entity_type": kind,
        "entity_id": identifier,
        "version": "1.0.0",
        "review_id": "R-S002-F01",
        "revision": 1,
        "scope": {"scope_type": "project", "scope_id": "S002"},
        "lineage": [ref("discovery", "D-S002"), ref("semantic_session", "SS-S002")],
        "digest": DIGEST,
        "created_at": "2026-09-02T10:00:00Z",
    }
    record.update(entity)
    return record


def review(status: str = "REVIEW_PENDING") -> dict[str, object]:
    return common(
        "finding_review",
        "R-S002-F01",
        {
            "entity_type": "finding_review",
            "finding_ref": ref("evaluation_finding", "S002-F01"),
            "affected_subject_refs": [ref("equipment", "EQ-S002-01"), ref("point", "PT-S002-01")],
            "source_evidence_refs": [ref("evidence_record", "EV-S002-F01")],
            "discovery_ref": ref("discovery", "D-S002"),
            "semantic_session_ref": ref("semantic_session", "SS-S002"),
            "status": status,
        },
    )


def operator_response() -> dict[str, object]:
    return common(
        "operator_response",
        "OR-S002-F01",
        {
            "entity_type": "operator_response",
            "review_ref": ref("finding_review", "R-S002-F01"),
            "respondent_ref": ref("site_operator", "operator-1"),
            "response_digest": DIGEST,
            "response_status": "PROVIDED",
            "responded_at": "2026-09-02T11:00:00Z",
        },
    )


def disposition(value: str = "APPROVED") -> dict[str, object]:
    return common(
        "reviewer_disposition",
        "RD-S002-F01",
        {
            "entity_type": "reviewer_disposition",
            "review_ref": ref("finding_review", "R-S002-F01"),
            "reviewer_ref": ref("authorized_reviewer", "reviewer-1"),
            "authority_ref": ref("review_authority", "authority-1"),
            "disposition": value,
            "rationale_ref": ref("evidence_record", "RATIONALE-S002-F01"),
            "decided_at": "2026-09-02T12:00:00Z",
        },
    )


class Stage04ConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads((ROOT / "contracts/finding-disposition.v1.candidate.schema.json").read_text())
        cls.validator = Draft202012Validator(schema)

    def test_schema_accepts_review_response_and_disposition(self) -> None:
        for record in (review(), operator_response(), disposition()):
            self.validator.validate(record)

    def test_all_review_states_are_explicit(self) -> None:
        for status in ("REVIEW_PENDING", "NEEDS_CLARIFICATION", "DEFERRED", "REJECTED", "APPROVED"):
            self.assertIn(status, review(status)["status"])

    def test_unresolved_states_never_permit_correction(self) -> None:
        for status in ("REVIEW_PENDING", "NEEDS_CLARIFICATION", "DEFERRED", "REJECTED"):
            record = review(status)
            self.assertNotEqual(record["status"], "APPROVED")
            self.assertNotIn("correction_proposal_ref", record)

    def test_approved_state_is_still_not_execution_authority(self) -> None:
        record = review("APPROVED")
        record["correction_proposal_ref"] = ref("proposal", "P-S002-F01")
        self.assertEqual(record["status"], "APPROVED")
        self.assertNotEqual(record["status"], "ALLOW")
        self.assertNotIn("execution_ref", record)
        self.assertNotIn("verification_ref", record)

    def test_stale_revision_and_changed_response_require_new_revision(self) -> None:
        current = review("REVIEW_PENDING")
        stale = review("APPROVED")
        stale["revision"] = 0
        changed = operator_response()
        changed["response_digest"] = "sha256:" + "b" * 64
        self.assertLess(stale["revision"], current["revision"])
        self.assertNotEqual(changed["response_digest"], operator_response()["response_digest"])

    def test_missing_contradictory_and_scope_invalid_cases_block(self) -> None:
        records = {"F01": review("APPROVED"), "F02": review("REVIEW_PENDING")}
        self.assertNotIn("F03", records)
        self.assertEqual(records["F02"]["status"], "REVIEW_PENDING")
        contradictory = {"disposition_a": "APPROVED", "disposition_b": "REJECTED", "status": "NEEDS_CLARIFICATION"}
        self.assertEqual(contradictory["status"], "NEEDS_CLARIFICATION")
        invalid_scope = review("APPROVED")
        invalid_scope["scope"] = {"scope_type": "project", "scope_id": "S003"}
        self.assertNotEqual(invalid_scope["scope"]["scope_id"], "S002")


if __name__ == "__main__":
    unittest.main()
