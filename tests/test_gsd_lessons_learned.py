import unittest

from tests.test_contracts import validate


class GsdLessonsLearnedTests(unittest.TestCase):
    def test_every_run_can_emit_an_evidence_linked_lesson(self):
        validate("gsd-learning.v1.schema.json", {
            "schema": "gsd-learning.v1",
            "id": "lesson.phase-020.001",
            "version": "1.0.0",
            "entity_type": "observation",
            "statement": "The reviewer PASS routed to Forge and did not complete the phase.",
            "evidence": [
                {"id": "phase-020-review-cycle-002", "version": "1.0.0"},
                {"id": "phase-020-completion-gate", "version": "1.0.0"},
            ],
            "confidence": "high",
            "observed_at": "2026-09-02T12:00:00Z",
            "session_refs": [{"id": "session-020", "version": "1.0.0"}],
        })

    def test_improvement_candidate_remains_proposed_until_governed(self):
        candidate = {
            "schema": "gsd-learning.v1",
            "id": "candidate.phase-020.001",
            "version": "1.0.0",
            "entity_type": "procedural_candidate",
            "observation_refs": [{"id": "lesson.phase-020.001", "version": "1.0.0"}],
            "pattern_refs": [],
            "proposed_change": "Keep the completion gate before the completed status.",
            "provenance": [{"id": "session-020", "version": "1.0.0"}],
            "status": "proposed",
            "created_at": "2026-09-02T12:00:00Z",
            "affected_capability": {"id": "gsd-master", "version": "3.3.0"},
        }
        validate("gsd-learning.v1.schema.json", candidate)
        self.assertEqual(candidate["status"], "proposed")

    def test_observation_cannot_smuggle_in_adoption_authority(self):
        with self.assertRaises(Exception):
            validate("gsd-learning.v1.schema.json", {
                "schema": "gsd-learning.v1",
                "id": "lesson.phase-020.002",
                "version": "1.0.0",
                "entity_type": "observation",
                "statement": "Automatically update the GSD skill.",
                "evidence": [{"id": "phase-020-review", "version": "1.0.0"}],
                "confidence": "high",
                "observed_at": "2026-09-02T12:00:00Z",
                "session_refs": [{"id": "session-020", "version": "1.0.0"}],
                "adopt": True,
            })


if __name__ == "__main__":
    unittest.main()
