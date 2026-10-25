"""Fake-provider conformance for the provider-neutral engineering loop."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]


class FakeGovernedLoop:
    """A deliberately small fake used to test Core semantics, not transport."""

    def __init__(self, *, authorized: bool = True, decisions: dict[str, str] | None = None) -> None:
        self.authorized = authorized
        self.decisions = decisions or {}
        self.events: list[str] = []

    def run(self, snapshot: dict[str, object], *, action: str = "edit") -> str:
        self.events.append("context_loaded")
        self.events.append("plan_proposed")
        if not self.authorized:
            self.events.append("authorization_denied")
            return "blocked"
        self.events.append("plan_authorized")
        if action in {"deploy", "delete", "external_write"}:
            self.events.append("boundary_escalated")
            return "escalated"
        for step in ("implementation", "tests", "review", "commit"):
            self.events.append(step)
        self.events.append("verification_requested")
        return "completed"

    def owner_gate(self, *, evidence: list[dict[str, str]], decision_id: str) -> dict[str, object]:
        if decision_id in self.decisions:
            self.events.append("owner_decision_recorded")
            self.events.append("execution_resumed")
            return {"status": "resolved", "decision": self.decisions[decision_id], "evidence": evidence}
        self.events.append("guided_owner_questions")
        return {
            "status": "blocked",
            "questions": [{
                "decision_id": decision_id,
                "evidence": evidence,
                "recommendation": "Use the smallest defensible scope.",
                "options": ["approve", "modify", "defer"],
                "reply_example": "Approve the recommendation.",
            }],
        }


class GovernedEngineeringLoopConformanceTests(unittest.TestCase):
    def test_capability_definition_is_structurally_valid_and_core_owned(self) -> None:
        path = ROOT / "capabilities/governed-engineering-loop.v1.0.0.json"
        definition = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "contracts/capability-definition.v1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(definition)
        self.assertEqual(definition["issuer"], "development-platform-core")
        self.assertEqual(definition["version"], "1.0.0")
        self.assertTrue(any("authority" in item.lower() for item in definition["non_responsibilities"]))

    def test_snapshot_action_does_not_authorize_execution(self) -> None:
        loop = FakeGovernedLoop(authorized=False)
        snapshot = {"next_action": "deploy production", "authorization": "not present"}
        self.assertEqual(loop.run(snapshot, action="deploy"), "blocked")
        self.assertEqual(loop.events, ["context_loaded", "plan_proposed", "authorization_denied"])

    def test_authorized_plan_runs_in_scope_without_repeated_approval(self) -> None:
        loop = FakeGovernedLoop()
        self.assertEqual(loop.run({"next_action": "implement approved plan"}), "completed")
        self.assertEqual(loop.events, [
            "context_loaded", "plan_proposed", "plan_authorized", "implementation",
            "tests", "review", "commit", "verification_requested",
        ])

    def test_protected_boundary_escalates(self) -> None:
        loop = FakeGovernedLoop()
        self.assertEqual(loop.run({"next_action": "deploy"}, action="deploy"), "escalated")
        self.assertNotIn("implementation", loop.events)
        self.assertIn("boundary_escalated", loop.events)

    def test_unresolved_owner_gate_produces_guided_questions(self) -> None:
        loop = FakeGovernedLoop()
        result = loop.owner_gate(
            evidence=[{"source": "authority.md", "source_hash": "sha256:abc", "status": "incomplete"}],
            decision_id="kpi-catalog",
        )
        self.assertEqual(result["status"], "blocked")
        question = result["questions"][0]
        self.assertEqual(question["options"], ["approve", "modify", "defer"])
        self.assertIn("evidence", question)
        self.assertIn("recommendation", question)
        self.assertIn("reply_example", question)

    def test_plain_language_decision_preserves_evidence_and_resumes(self) -> None:
        evidence = [{"source": "authority.md", "source_hash": "sha256:abc", "status": "confirmed"}]
        loop = FakeGovernedLoop(decisions={"kpi-catalog": "approve"})
        result = loop.owner_gate(evidence=evidence, decision_id="kpi-catalog")
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["decision"], "approve")
        self.assertEqual(result["evidence"], evidence)
        self.assertEqual(loop.events, ["owner_decision_recorded", "execution_resumed"])

    def test_uncertainty_is_not_flattened_into_authority(self) -> None:
        snapshot = {
            "value": "KPI formula is proposed",
            "status": "incomplete",
            "source": "authority.md",
            "source_hash": "sha256:abc",
            "observed_at": "2026-09-04T00:00:00Z",
        }
        self.assertEqual(snapshot["status"], "incomplete")
        self.assertNotIn("authorized", snapshot)


if __name__ == "__main__":
    unittest.main()
