"""Conformance fixtures for the unapproved derived working-state candidate."""

from __future__ import annotations

import hashlib
import json
import unittest


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def candidate(*, gsd: dict, session: dict, session_id: str = "session-2") -> dict:
    sources = {"gsd_ref": gsd["ref"], "session_record_refs": [session["ref"]]}
    return {
        "candidate_id": f"checkpoint:{session_id}",
        "project_id": "example-project",
        "session_id": session_id,
        **sources,
        "source_digests": {"gsd": digest(gsd), "session": digest(session)},
        "objective": gsd["objective"],
        "phase": gsd["phase"],
        "completed_summary": list(gsd["completed"]),
        "discovery_summary": list(session["discoveries"]),
        "failure_summary": list(session["failures"]),
        "next_step": gsd["next"],
        "blocker": gsd["blocker"],
        "checkpointed_at": "2026-09-01T10:00:00Z",
    }


def recover(value: dict, *, gsd: dict, session: dict) -> dict:
    expected = candidate(gsd=gsd, session=session, session_id=value["session_id"])
    expected["candidate_id"] = value["candidate_id"]
    return value if value.get("source_digests") == expected["source_digests"] else expected


class WorkingStateCandidateConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gsd = {
            "ref": "gsd:task-1",
            "objective": "implement X",
            "phase": 3,
            "completed": ["A", "B"],
            "next": "E",
            "blocker": "none",
        }
        self.session = {
            "ref": "session-record:session-1",
            "discoveries": ["C"],
            "failures": ["D"],
        }

    def test_candidate_contains_only_bounded_resume_material(self) -> None:
        value = candidate(gsd=self.gsd, session=self.session)
        self.assertEqual(value["completed_summary"], ["A", "B"])
        self.assertEqual(value["discovery_summary"], ["C"])
        self.assertEqual(value["failure_summary"], ["D"])
        self.assertNotIn("prompt", value)
        self.assertNotIn("tool_output", value)
        self.assertNotIn("authorization", value)
        self.assertNotIn("policy_decision", value)

    def test_candidate_references_authorities_and_digests_them(self) -> None:
        value = candidate(gsd=self.gsd, session=self.session)
        self.assertEqual(value["gsd_ref"], "gsd:task-1")
        self.assertEqual(value["session_record_refs"], ["session-record:session-1"])
        self.assertEqual(value["source_digests"]["gsd"], digest(self.gsd))

    def test_changed_gsd_regenerates_candidate(self) -> None:
        value = candidate(gsd=self.gsd, session=self.session)
        changed = {**self.gsd, "completed": ["A", "B", "E"], "next": "F"}
        recovered = recover(value, gsd=changed, session=self.session)
        self.assertEqual(recovered["completed_summary"], ["A", "B", "E"])
        self.assertEqual(recovered["next_step"], "F")

    def test_changed_session_regenerates_candidate(self) -> None:
        value = candidate(gsd=self.gsd, session=self.session)
        changed = {**self.session, "failures": ["D", "G"]}
        recovered = recover(value, gsd=self.gsd, session=changed)
        self.assertEqual(recovered["failure_summary"], ["D", "G"])

    def test_partial_candidate_is_rejected(self) -> None:
        value = candidate(gsd=self.gsd, session=self.session)
        del value["source_digests"]
        recovered = recover(value, gsd=self.gsd, session=self.session)
        self.assertEqual(recovered, candidate(gsd=self.gsd, session=self.session))

    def test_candidate_cannot_authorize_execution(self) -> None:
        value = candidate(gsd=self.gsd, session=self.session)
        self.assertFalse(any(key in value for key in ("authorization", "execute", "approval")))

    def test_resume_links_new_attempt_without_rewriting_prior_session(self) -> None:
        value = candidate(gsd=self.gsd, session=self.session, session_id="session-2")
        self.assertEqual(value["session_id"], "session-2")
        self.assertEqual(value["session_record_refs"], ["session-record:session-1"])


if __name__ == "__main__":
    unittest.main()
