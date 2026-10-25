from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver

from adapters.agent_adapter import AgentAdapter, AgentAdapterError


ROOT = Path(__file__).parents[1]


def context() -> dict:
    return {
        "schema": "agent-startup-context.v1",
        "project_id": "rewards-os",
        "repository_root": "/workspace/rewards-os",
        "knowledge_root": "vault/",
        "planning_root": "vault/00-GSD-Phases/",
        "current_objective": "qualify the adapter",
        "active_phase": "001",
        "session": {"session_id": "session-001"},
        "repository_intelligence": {
            "schema": "repository-intelligence.v1",
            "status": "CURRENT",
            "provider": "fake-graph",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "indexed_revision": "abc123",
            "trusted": True,
            "relevant_files": [],
            "relevant_symbols": [],
            "notes": [],
            "freshness_evidence": [],
        },
        "agents": {"claude": True, "codex": True, "opencode": True},
        "session_brief": {"status": "unavailable", "path": None, "reason": "disabled"},
        "runtime_history": {"status": "unavailable", "recent_runs": [], "reason": "disabled"},
    }


class AgentAdapterTests(unittest.TestCase):
    def test_builds_schema_valid_request_for_each_provider(self) -> None:
        schema_path = ROOT / "contracts/agent-adapter.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        resolver = RefResolver(schema_path.as_uri(), schema)
        adapter = AgentAdapter()
        for agent in ("claude", "codex", "opencode"):
            request = adapter.build(
                agent=agent,
                request_id=f"request-{agent}",
                startup_context=context(),
                mode="interactive",
            ).to_dict()
            Draft202012Validator(schema, resolver=resolver).validate(request)
            self.assertEqual(request["agent"], agent)
            self.assertEqual(request["startup_context"]["project_id"], "rewards-os")

    def test_preserves_context_without_sharing_mutable_state(self) -> None:
        original = context()
        request = AgentAdapter().build(
            agent="codex",
            request_id="request-001",
            startup_context=original,
            mode="read_only",
            task_manifest="tasks/manifest.yaml",
        )
        payload = request.to_dict()
        payload["startup_context"]["project_id"] = "tampered"
        self.assertEqual(request.startup_context["project_id"], "rewards-os")
        self.assertEqual(original["project_id"], "rewards-os")
        self.assertEqual(original["current_objective"], "qualify the adapter")
        self.assertEqual(request.task_manifest, "tasks/manifest.yaml")

    def test_rejects_unknown_agent_mode_and_context_version(self) -> None:
        adapter = AgentAdapter()
        cases = (
            {"agent": "gemini"},
            {"agent": "codex", "mode": "streaming"},
            {"agent": "codex", "startup_context": {"schema": "other.v1"}},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(AgentAdapterError):
                adapter.build(
                    agent=case.get("agent", "codex"),
                    request_id="request-001",
                    startup_context=case.get("startup_context", context()),
                    mode=case.get("mode", "interactive"),
                )


if __name__ == "__main__":
    unittest.main()
