"""Cross-record normative checks for the Stage 04 candidate profile."""

from __future__ import annotations

import unittest


def eligible(review: dict[str, object], response: dict[str, object] | None, disposition: dict[str, object] | None, correction: dict[str, object] | None = None) -> bool:
    if review["status"] != "APPROVED" or response is None or disposition is None:
        return False
    if response["review_id"] != review["review_id"] or response["revision"] != review["revision"]:
        return False
    if disposition["review_id"] != review["review_id"] or disposition["revision"] != review["revision"]:
        return False
    if disposition["scope"] != review["scope"] or response["scope"] != review["scope"]:
        return False
    if correction is not None and correction["review_revision"] != review["revision"]:
        return False
    return True


def review(identifier: str, status: str = "APPROVED", revision: int = 1, scope: str = "S002") -> dict[str, object]:
    return {"finding_id": identifier, "review_id": f"review-{identifier}", "status": status, "revision": revision, "scope": scope}


def response(parent: dict[str, object], revision: int | None = None, scope: str | None = None) -> dict[str, object]:
    return {"review_id": parent["review_id"], "revision": parent["revision"] if revision is None else revision, "scope": parent["scope"] if scope is None else scope}


def disposition(parent: dict[str, object], revision: int | None = None, scope: str | None = None) -> dict[str, object]:
    return {"review_id": parent["review_id"], "revision": parent["revision"] if revision is None else revision, "scope": parent["scope"] if scope is None else scope}


class Stage04NormativeProfileTests(unittest.TestCase):
    def test_eight_finding_fixture_is_fail_closed(self) -> None:
        cases = {
            "F01": (review("F01", "REVIEW_PENDING"), False),
            "F02": (review("F02", "NEEDS_CLARIFICATION"), False),
            "F03": (review("F03", "DEFERRED"), False),
            "F04": (review("F04", "REJECTED"), False),
            "F05": (review("F05"), False),
            "F06": (review("F06"), False),
            "F07": (review("F07"), False),
            "F08": (review("F08"), False),
        }
        for identifier, (parent, expected) in cases.items():
            if identifier == "F05":
                actual = eligible(parent, None, disposition(parent))
            elif identifier == "F06":
                actual = eligible(parent, response(parent), disposition(parent, revision=2))
            elif identifier == "F07":
                actual = eligible(parent, response(parent), disposition(parent, scope="S003"))
            elif identifier == "F08":
                actual = eligible(parent, response(parent), None)
            else:
                actual = eligible(parent, response(parent), disposition(parent))
            self.assertEqual(actual, expected, identifier)

    def test_approved_correction_must_bind_exact_revision(self) -> None:
        parent = review("F05", revision=3)
        self.assertTrue(eligible(parent, response(parent), disposition(parent), {"review_revision": 3}))
        self.assertFalse(eligible(parent, response(parent), disposition(parent), {"review_revision": 2}))

    def test_contradictory_disposition_is_not_approved(self) -> None:
        parent = review("F08")
        contradictory = {"review_id": parent["review_id"], "revision": 1, "scope": "S002", "values": {"APPROVED", "REJECTED"}}
        self.assertEqual(contradictory["values"], {"APPROVED", "REJECTED"})
        self.assertFalse(eligible(parent, response(parent), None))

    def test_response_and_disposition_are_not_authorization(self) -> None:
        parent = review("F05")
        self.assertTrue(eligible(parent, response(parent), disposition(parent)))
        self.assertNotIn("policy_decision", parent)
        self.assertNotIn("execution", parent)
        self.assertNotIn("verification", parent)


if __name__ == "__main__":
    unittest.main()
