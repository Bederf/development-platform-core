import hashlib
import json
import unittest
from pathlib import Path

from adapters.radix.context_projection import StartupContextProjector, estimate_tokens


ROOT = Path(__file__).parents[1]


class ContextOptimizationBaselineTests(unittest.TestCase):
    def test_fixture_is_reproducible_and_current_projection_defers_oversized_sections(self) -> None:
        fixture = json.loads((ROOT / "fixtures/context/context-optimization-workloads-v1.json").read_text())
        projector = StartupContextProjector(max_tokens=1000)
        for workload in fixture["workloads"]:
            text = workload["repeat"] * workload["repeat_count"]
            section = {
                "source_id": workload["id"],
                "path": f"/project/{workload['id']}",
                "section_id": f"{workload['id']}-section",
                "kind": "active",
                "authority": "reference",
                "text": text,
                "content_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                "estimated_tokens": estimate_tokens(text),
            }
            projection = projector.project(
                project_id="benchmark",
                objective=workload["objective"],
                tasks=[],
                brief={"status": "unavailable", "path": None, "text": None},
                sections=[section],
                source_documents=[],
            )
            self.assertGreater(estimate_tokens(text), 1000)
            self.assertTrue(projection["budget"]["truncated"], workload["id"])
            self.assertEqual(projection["inline_sections"], [], workload["id"])
            self.assertEqual(len(projection["on_demand_sources"]), 1, workload["id"])


if __name__ == "__main__":
    unittest.main()
