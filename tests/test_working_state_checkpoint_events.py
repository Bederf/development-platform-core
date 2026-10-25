from __future__ import annotations

import unittest
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from adapters.radix.working_state_events import (
    CheckpointEventError,
    CheckpointEventProducer,
    validate_checkpoint_event,
)


class CheckpointEventProducerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.producer = CheckpointEventProducer(project_id="example-project")
        self.gsd = {
            "ref": "gsd:task-1",
            "objective": "implement X",
            "phase": 3,
            "next": "E",
            "blocker": "none",
        }

    def event(self) -> dict:
        return self.producer.produce(
            session_id="session-2",
            gsd=self.gsd,
            session_record_refs=["session-record:session-1"],
            summaries={"completed": ["A", "B"], "discoveries": ["C"], "failures": ["D"]},
            reason="handoff",
        )

    def test_event_is_versioned_bounded_and_valid(self) -> None:
        event = self.event()
        validate_checkpoint_event(event, project_id="example-project")
        schema = json.loads(
            (Path(__file__).parents[1] / "contracts/working-state-checkpoint-event.v1.schema.json").read_text()
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(event)
        self.assertEqual(event["schema"], "working-state-checkpoint-event.v1")
        self.assertEqual(event["next_step"], "E")
        self.assertNotIn("policy_decision", event)

    def test_only_declared_boundary_is_allowed(self) -> None:
        with self.assertRaises(CheckpointEventError):
            self.producer.produce(
                session_id="session-2", gsd=self.gsd, session_record_refs=[], summaries={}, reason="model-turn"
            )

    def test_forbidden_material_and_unbounded_summary_are_rejected(self) -> None:
        with self.assertRaises(CheckpointEventError):
            self.producer.produce(
                session_id="session-2", gsd=self.gsd, session_record_refs=[], summaries={"prompt": ["x"]}, reason="handoff"
            )
        with self.assertRaises(CheckpointEventError):
            self.producer.produce(
                session_id="session-2", gsd=self.gsd, session_record_refs=[], summaries={"completed": ["x" * 241]}, reason="handoff"
            )

    def test_event_tampering_and_cross_project_are_rejected(self) -> None:
        event = self.event()
        event["next_step"] = "unsafe"
        with self.assertRaises(CheckpointEventError):
            validate_checkpoint_event(event, project_id="example-project")
        with self.assertRaises(CheckpointEventError):
            validate_checkpoint_event(self.event(), project_id="other-project")


if __name__ == "__main__":
    unittest.main()
