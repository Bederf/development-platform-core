"""Exploratory recovery fixtures for a disposable AgentWorkingState.

The fake checkpoint is deliberately derived from authoritative GSD and
session records. It is not a proposed contract or an execution authority.
"""

from __future__ import annotations

import hashlib
import unittest


def digest(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def derive_working_state(gsd: dict, session: dict) -> dict:
    return {
        "objective": gsd["objective"],
        "phase": gsd["phase"],
        "completed": list(gsd["completed"]),
        "discoveries": list(session["discoveries"]),
        "failures": list(session["failures"]),
        "next": gsd["next"],
        "blocker": gsd["blocker"],
        "authority_digest": digest({"gsd": gsd, "session": session}),
    }


def recover(checkpoint: dict, gsd: dict, session: dict) -> dict:
    expected = derive_working_state(gsd, session)
    if checkpoint.get("authority_digest") != expected["authority_digest"]:
        return expected
    return checkpoint


class WorkingStateRecoveryConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gsd = {
            "objective": "implement X",
            "phase": 3,
            "completed": ["A", "B"],
            "next": "E",
            "blocker": "none",
        }
        self.session = {"discoveries": ["C"], "failures": ["D"]}

    def test_checkpoint_recovers_all_required_resume_facts(self) -> None:
        checkpoint = derive_working_state(self.gsd, self.session)
        recovered = recover(checkpoint, self.gsd, self.session)
        self.assertEqual(recovered["objective"], "implement X")
        self.assertEqual(recovered["phase"], 3)
        self.assertEqual(recovered["completed"], ["A", "B"])
        self.assertEqual(recovered["discoveries"], ["C"])
        self.assertEqual(recovered["failures"], ["D"])
        self.assertEqual(recovered["next"], "E")
        self.assertEqual(recovered["blocker"], "none")

    def test_stale_checkpoint_is_regenerated_from_authorities(self) -> None:
        stale = derive_working_state(
            {**self.gsd, "phase": 2, "next": "C"}, {"discoveries": [], "failures": []}
        )
        recovered = recover(stale, self.gsd, self.session)
        self.assertEqual(recovered["phase"], 3)
        self.assertEqual(recovered["next"], "E")
        self.assertEqual(recovered["discoveries"], ["C"])

    def test_authoritative_change_invalidates_checkpoint(self) -> None:
        checkpoint = derive_working_state(self.gsd, self.session)
        changed = {**self.gsd, "completed": ["A", "B", "E"], "next": "F"}
        recovered = recover(checkpoint, changed, self.session)
        self.assertEqual(recovered["completed"], ["A", "B", "E"])
        self.assertEqual(recovered["next"], "F")

    def test_corrupted_checkpoint_is_replaced(self) -> None:
        checkpoint = {"objective": "wrong", "phase": 99, "authority_digest": "tampered"}
        recovered = recover(checkpoint, self.gsd, self.session)
        self.assertEqual(recovered, derive_working_state(self.gsd, self.session))

    def test_checkpoint_cannot_authorize_execution(self) -> None:
        checkpoint = derive_working_state(self.gsd, self.session)
        self.assertNotIn("policy_decision", checkpoint)
        self.assertNotIn("authorization", checkpoint)
        self.assertNotIn("execute", checkpoint)

    def test_session_history_remains_distinct_from_working_state(self) -> None:
        checkpoint = derive_working_state(self.gsd, self.session)
        self.assertNotEqual(checkpoint["authority_digest"], digest(self.session))
        self.assertEqual(self.session["failures"], ["D"])


if __name__ == "__main__":
    unittest.main()
