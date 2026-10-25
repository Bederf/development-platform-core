"""Final projection-linkage gate for untrusted content.

This test asks whether the existing startup projection can carry immutable
content-assessment and handling references without a schema change.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "contracts/startup-context-projection.v1.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def projection() -> dict:
    return {
        "schema": "startup-context-projection.v1",
        "project_id": "project-a",
        "objective": "review retrieved content",
        "task_selection": {"strategy": "objective_relevance", "task_id": None, "reason": "fixture"},
        "budget": {"max_tokens": 100, "estimated_tokens": 10, "truncated": False},
        "brief": {"status": "unavailable", "path": None, "text": None},
        "inline_sections": [
            {
                "source_id": "web-example",
                "path": "external://example",
                "section_id": "content-1",
                "kind": "reference",
                "authority": "reference",
                "text": "external reference",
                "content_hash": "sha256:" + "a" * 64,
                "estimated_tokens": 3,
            }
        ],
        "on_demand_sources": [],
    }


class UntrustedContentProjectionLinkageTests(unittest.TestCase):
    def test_existing_projection_is_valid_without_assessment_metadata(self) -> None:
        VALIDATOR.validate(projection())

    def test_assessment_reference_is_not_currently_allowed_on_projection(self) -> None:
        candidate = projection()
        candidate["inline_sections"][0]["assessment_ref"] = "evaluation://content-1"

        with self.assertRaises(ValidationError):
            VALIDATOR.validate(candidate)

    def test_handling_reference_is_not_currently_allowed_on_projection(self) -> None:
        candidate = projection()
        candidate["inline_sections"][0]["handling_ref"] = "policy://content-handling-1"

        with self.assertRaises(ValidationError):
            VALIDATOR.validate(candidate)

    def test_source_and_digest_remain_the_current_projection_linkage(self) -> None:
        section = projection()["inline_sections"][0]

        self.assertEqual(section["source_id"], "web-example")
        self.assertTrue(section["content_hash"].startswith("sha256:"))
        self.assertNotIn("assessment_ref", section)
        self.assertNotIn("handling_ref", section)


if __name__ == "__main__":
    unittest.main()
