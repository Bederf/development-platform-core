"""Provider-free composition checks for derived agent working state.

This is a qualification fixture, not a promoted contract. The projection
references existing GSD/session authorities and is disposable.
"""

from __future__ import annotations

import hashlib
import json
import unittest


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def compose_checkpoint(gsd: dict, session: dict) -> dict:
    authority = {"gsd": gsd, "session": session}
    return {
        "objective": gsd["objective"],
        "phase": gsd["phase"],
        "completed": list(gsd["completed"]),
        "discoveries": list(session["discoveries"]),
        "failures": list(session["failures"]),
        "next": gsd["next"],
        "blocker": gsd["blocker"],
        "authority_digest": _digest(authority),
    }


def recover_checkpoint(checkpoint: dict, gsd: dict, session: dict) -> dict:
    expected = compose_checkpoint(gsd, session)
    return checkpoint if checkpoint.get("authority_digest") == expected["authority_digest"] else expected


class WorkingStateCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gsd = {
            "objective": "implement X",
            "phase": 3,
            "completed": ["A", "B"],
            "next": "E",
            "blocker": "none",
        }
        self.session = {"discoveries": ["C"], "failures": ["D"]}

    def test_composition_preserves_resume_facts_without_new_authority(self) -> None:
        checkpoint = compose_checkpoint(self.gsd, self.session)
        self.assertEqual(checkpoint["objective"], self.gsd["objective"])
        self.assertEqual(checkpoint["discoveries"], self.session["discoveries"])
        self.assertNotIn("authorization", checkpoint)
        self.assertNotIn("policy_decision", checkpoint)
        self.assertNotIn("execute", checkpoint)

    def test_authoritative_change_rebuilds_projection(self) -> None:
        checkpoint = compose_checkpoint(self.gsd, self.session)
        changed_gsd = {**self.gsd, "completed": ["A", "B", "E"], "next": "F"}
        recovered = recover_checkpoint(checkpoint, changed_gsd, self.session)
        self.assertEqual(recovered["completed"], ["A", "B", "E"])
        self.assertEqual(recovered["next"], "F")

    def test_corruption_rebuilds_projection(self) -> None:
        recovered = recover_checkpoint(
            {"objective": "tampered", "authority_digest": "bad"}, self.gsd, self.session
        )
        self.assertEqual(recovered, compose_checkpoint(self.gsd, self.session))

    def test_unchanged_authorities_allow_checkpoint_reuse(self) -> None:
        checkpoint = compose_checkpoint(self.gsd, self.session)
        self.assertIs(recover_checkpoint(checkpoint, self.gsd, self.session), checkpoint)

    def test_composition_does_not_merge_session_history_into_task_authority(self) -> None:
        checkpoint = compose_checkpoint(self.gsd, self.session)
        self.assertEqual(checkpoint["completed"], ["A", "B"])
        self.assertEqual(checkpoint["failures"], ["D"])
        self.assertNotEqual(checkpoint["authority_digest"], _digest(self.session))


if __name__ == "__main__":
    unittest.main()
