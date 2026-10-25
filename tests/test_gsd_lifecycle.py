from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from adapters.gsd_lifecycle import GsdLifecycleAdapter, GsdLifecycleError


ROOT = Path(__file__).parents[1]


class GsdLifecycleAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads((ROOT / "contracts/gsd-planning-lifecycle.v1.schema.json").read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema)
        self.adapter = GsdLifecycleAdapter()

    def test_builds_schema_valid_record_and_preserves_evidence_reference(self) -> None:
        record = self.adapter.create(
            phase_id="001",
            phase_status="IN_PROGRESS",
            lifecycle_events=[{
                "event": "STARTED",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "evidence_ref": "phase-001-start",
            }],
        )
        self.validator.validate(record)
        self.assertEqual(record["lifecycle_events"][0]["evidence_ref"], "phase-001-start")

    def test_append_does_not_mutate_input_record(self) -> None:
        record = self.adapter.create(phase_id="001", phase_status="AUTHORIZED")
        updated = self.adapter.append(record, event="GOVERNED", evidence_ref="decision-001")
        self.assertEqual(record["lifecycle_events"], [])
        self.assertEqual(updated["lifecycle_events"][0]["event"], "GOVERNED")
        self.validator.validate(updated)

    def test_rejects_unknown_status_event_and_bad_evidence(self) -> None:
        with self.assertRaises(GsdLifecycleError):
            self.adapter.create(phase_id="001", phase_status="RUNNING")
        with self.assertRaises(GsdLifecycleError):
            self.adapter.create(phase_id="001", phase_status="AUTHORIZED", lifecycle_events=[{"event": "DONE", "occurred_at": "now"}])
        with self.assertRaises(GsdLifecycleError):
            self.adapter.append({"schema": "gsd-planning-lifecycle.v1", "phase_id": "001", "phase_status": "AUTHORIZED", "lifecycle_events": []}, event="STARTED", evidence_ref=3)


if __name__ == "__main__":
    unittest.main()
