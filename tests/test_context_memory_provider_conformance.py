import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


class FakeMemoryProvider:
    """Test double describing the candidate memory-provider boundary only."""

    def __init__(self, items: list[dict]):
        self.items = items

    def retrieve(self, *, project_id: str, query: str, limit: int = 3) -> list[dict]:
        if limit < 1 or limit > 100:
            raise ValueError("retrieval limit must be between 1 and 100")
        matches = [
            item
            for item in self.items
            if item["project_id"] == project_id
            and item["authority_class"] == "informational"
            and query.lower() in item["content"].lower()
        ]
        return sorted(matches, key=lambda item: (-item["relevance"], item["memory_id"]))[:limit]


def memory_item(memory_id: str, project_id: str, content: str, *, relevance: float) -> dict:
    return {
        "memory_id": memory_id,
        "project_id": project_id,
        "source_ref": f"session:{memory_id}",
        "source_digest": hashlib.sha256(content.encode()).hexdigest(),
        "content": content,
        "authority_class": "informational",
        "trust_class": "observed",
        "relevance": relevance,
    }


class ContextMemoryProviderConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = Path(__file__).parents[1] / "fixtures/context/session-memory-replay-v1.json"
        fixture_schema = json.loads(
            (fixture.parent / "session-memory-replay-v1.schema.json").read_text(encoding="utf-8")
        )
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        Draft202012Validator(fixture_schema).validate(payload)
        self.assertEqual(payload["schema"], "session-memory-replay.v1")
        for item in payload["records"]:
            self.assertEqual(
                item["source_digest"],
                hashlib.sha256(item["content"].encode()).hexdigest(),
            )
        self.provider = FakeMemoryProvider(payload["records"])

    def test_retrieval_is_project_scoped_and_relevance_ordered(self) -> None:
        result = self.provider.retrieve(project_id="project-a", query="dependency check")
        self.assertEqual([item["memory_id"] for item in result], ["memory-a", "memory-b"])

    def test_retrieval_is_bounded(self) -> None:
        result = self.provider.retrieve(project_id="project-a", query="dependency", limit=1)
        self.assertEqual(len(result), 1)

    def test_invalid_retrieval_limits_fail_closed(self) -> None:
        for limit in (0, -1, 101):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "between 1 and 100"):
                self.provider.retrieve(project_id="project-a", query="dependency", limit=limit)

    def test_items_carry_provenance_and_non_authoritative_metadata(self) -> None:
        item = self.provider.retrieve(project_id="project-a", query="failed")[0]
        self.assertTrue(item["source_ref"])
        self.assertRegex(item["source_digest"], r"^[a-f0-9]{64}$")
        self.assertEqual(item["authority_class"], "informational")
        self.assertEqual(item["trust_class"], "observed")

    def test_replay_items_preserve_execution_lineage_and_session_identity(self) -> None:
        item = self.provider.retrieve(project_id="project-a", query="dependency")[0]
        self.assertEqual(item["session_id"], "session-a")
        self.assertEqual(item["execution_id"], "execution-a")
        self.assertEqual(item["lineage_id"], "lineage-a")

    def test_foreign_project_memory_is_not_retrievable(self) -> None:
        self.assertEqual(self.provider.retrieve(project_id="project-a", query="failed")[0]["project_id"], "project-a")

    def test_authoritative_sources_are_not_projected_as_memory(self) -> None:
        authoritative = memory_item(
            "memory-authoritative", "project-a", "dependency check failed", relevance=1.0
        )
        authoritative["authority_class"] = "authoritative"
        provider = FakeMemoryProvider(self.provider.items + [authoritative])
        result = provider.retrieve(project_id="project-a", query="dependency check")
        self.assertNotIn("memory-authoritative", [item["memory_id"] for item in result])


if __name__ == "__main__":
    unittest.main()
