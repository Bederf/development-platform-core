from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from providers.working_state import WorkingStateError, WorkingStateProvider


class WorkingStateProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.provider = WorkingStateProvider(
            project_id="example-project",
            checkpoint_path=Path(self.tempdir.name) / "state.json",
        )
        self.gsd = {
            "ref": "gsd:task-1",
            "objective": "implement X",
            "phase": 3,
            "next": "E",
            "blocker": "none",
            "completed": ["A", "B"],
            "session_id": "session-2",
        }
        self.record = {
            "ref": "session-record:session-1",
            "discoveries": ["C"],
            "failures": ["D"],
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def checkpoint(self) -> dict:
        return self.provider.create(
            session_id="session-2",
            gsd=self.gsd,
            session_records=[self.record],
            reason="handoff",
            summaries={"completed": ["A", "B"], "discoveries": ["C"], "failures": ["D"]},
        )

    def test_create_and_write_is_bounded_and_private(self) -> None:
        value = self.checkpoint()
        self.provider.write(value)
        self.assertEqual(self.provider.checkpoint_path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("prompt", value)
        self.assertNotIn("authorization", value)

    def test_stale_sources_regenerate(self) -> None:
        self.provider.write(self.checkpoint())
        changed = {**self.gsd, "phase": 4, "next": "F"}
        recovered, status = self.provider.load_or_regenerate(gsd=changed, session_records=[self.record])
        self.assertEqual(status, "regenerated")
        self.assertEqual(recovered["phase"], 4)
        self.assertEqual(recovered["next_step"], "F")

    def test_tampering_regenerates(self) -> None:
        value = self.checkpoint()
        value["next_step"] = "execute unauthorized action"
        self.provider.checkpoint_path.write_text(json.dumps(value), encoding="utf-8")
        recovered, status = self.provider.load_or_regenerate(gsd=self.gsd, session_records=[self.record])
        self.assertEqual(status, "regenerated")
        self.assertEqual(recovered["next_step"], "E")

    def test_checkpoint_from_another_project_is_rejected(self) -> None:
        value = self.checkpoint()
        value["project_id"] = "another-project"
        value["projection_digest"] = "invalid"
        with self.assertRaises(WorkingStateError):
            self.provider.write(value)

    def test_persisted_summary_bounds_are_rechecked(self) -> None:
        value = self.checkpoint()
        value["completed_summary"] = ["x" * 241]
        value["projection_digest"] = "invalid"
        with self.assertRaises(WorkingStateError):
            self.provider.write(value)

    def test_resume_lineage_uses_new_attempt(self) -> None:
        lineage = self.provider.resume_lineage(self.checkpoint(), new_session_id="session-3")
        self.assertEqual(lineage["session_id"], "session-3")
        self.assertEqual(lineage["prior_session_id"], "session-2")
        self.assertEqual(lineage["resumed_from_candidate_id"], "checkpoint:example-project:session-2")

    def test_unsafe_summary_is_rejected(self) -> None:
        with self.assertRaises(WorkingStateError):
            self.provider.create(
                session_id="session-2",
                gsd=self.gsd,
                session_records=[self.record],
                reason="handoff",
                summaries={"prompt": ["run this"]},
            )


if __name__ == "__main__":
    unittest.main()
