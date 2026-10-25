"""Provider-free conformance tests for the Tool Mediation boundary.

These tests deliberately define behavior before a production mediator exists.
They test authority and linkage invariants, not a particular implementation.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    decision_id: str
    authorization_use_id: str | None = None


@dataclass(frozen=True)
class Approval:
    actor: str
    tool: str
    target: str
    scope: str
    expires_at: datetime
    use_id: str
    consumed: bool = False


class FakePolicyAuthority:
    """Minimal policy provider used to test mediation invariants."""

    def __init__(
        self,
        *,
        allowed_tools: set[str],
        authorized_scope: str,
        required_risk: str = "high",
        approval_store: dict[str, Approval] | None = None,
    ) -> None:
        self.allowed_tools = allowed_tools
        self.authorized_scope = authorized_scope
        self.required_risk = required_risk
        self.decisions: list[Decision] = []
        self.approvals = approval_store if approval_store is not None else {}
        self._decision_number = 0

    def decide(
        self,
        *,
        actor: str,
        tool: str,
        target: str,
        requested_scope: str,
        risk: str | None,
        approval: Approval | None = None,
    ) -> Decision:
        self._decision_number += 1
        decision_id = f"decision-{self._decision_number}"
        if tool not in self.allowed_tools:
            return self._record(Decision("deny", "UNKNOWN_TOOL", decision_id))
        if risk is None or risk != self.required_risk:
            return self._record(Decision("deny", "RISK_NOT_EXPLICIT", decision_id))
        if requested_scope != self.authorized_scope:
            return self._record(Decision("deny", "SCOPE_NOT_AUTHORIZED", decision_id))
        if approval is not None:
            stored_approval = self.approvals.get(approval.use_id)
            if approval.actor != actor or approval.tool != tool or approval.target != target:
                return self._record(Decision("deny", "APPROVAL_MISMATCH", decision_id))
            if approval.scope != self.authorized_scope or approval.expires_at <= _now():
                return self._record(Decision("deny", "APPROVAL_INVALID", decision_id))
            if stored_approval is None or stored_approval.consumed:
                return self._record(Decision("deny", "APPROVAL_REPLAY", decision_id))
            self.approvals[approval.use_id] = Approval(**{**stored_approval.__dict__, "consumed": True})
            return self._record(Decision("allow", "APPROVED", decision_id, approval.use_id))
        return self._record(Decision("allow", "ALLOWED", decision_id))

    def issue_approval(self, *, actor: str, tool: str, target: str, scope: str, ttl_seconds: int = 60) -> Approval:
        approval = Approval(actor, tool, target, scope, _now() + timedelta(seconds=ttl_seconds), "approval-001")
        self.approvals[approval.use_id] = approval
        return approval

    def _record(self, decision: Decision) -> Decision:
        self.decisions.append(decision)
        return decision


class FakeHerdr:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def execute(self, *, decision: Decision, actor: str, tool: str, target: str, attempt_id: str) -> dict[str, str]:
        self.calls.append({"decision_id": decision.decision_id, "actor": actor, "tool": tool, "target": target, "attempt_id": attempt_id})
        return {"execution_id": "execution-001", "attempt_id": attempt_id, "status": "completed"}


class FakeForge:
    def verify(self, *, attempt_id: str, result: dict[str, str], reported_attempt_id: str | None, status: str) -> bool:
        return status == "PASSED" and reported_attempt_id == attempt_id and result["attempt_id"] == attempt_id


class FakeQuotaAuthority:
    """Small restart-safe quota double; storage is injected, not owned by policy."""

    def __init__(self, *, limit: int, state: dict[str, int]) -> None:
        self.limit = limit
        self.state = state

    def consume(self) -> bool:
        if self.state.get("count", 0) >= self.limit:
            return False
        self.state["count"] = self.state.get("count", 0) + 1
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ToolMediationConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = FakePolicyAuthority(allowed_tools={"read_code", "write_code"}, authorized_scope="project-A")
        self.herdr = FakeHerdr()
        self.forge = FakeForge()
        self.quota_limit: int | None = None
        self.quota_count = 0

    def mediate(self, *, actor: str = "agent-001", tool: str, target: str, scope: str, risk: str | None = "high", approval: Approval | None = None) -> tuple[Decision, dict[str, str] | None]:
        if self.quota_limit is not None and self.quota_count >= self.quota_limit:
            return Decision("deny", "QUOTA_EXCEEDED", "quota-decision"), None
        decision = self.policy.decide(
            actor=actor,
            tool=tool,
            target=target,
            requested_scope=scope,
            risk=risk,
            approval=approval,
        )
        if decision.outcome != "allow":
            return decision, None
        self.quota_count += 1
        return decision, self.herdr.execute(
            decision=decision,
            actor=actor,
            tool=tool,
            target=target,
            attempt_id="attempt-001",
        )

    def test_unknown_tool_is_denied_before_herdr(self) -> None:
        decision, result = self.mediate(tool="unknown-tool", target="x", scope="project-A")
        self.assertEqual(decision.outcome, "deny")
        self.assertEqual(decision.reason, "UNKNOWN_TOOL")
        self.assertIsNone(result)
        self.assertEqual(self.herdr.calls, [])

    def test_risk_must_be_explicit(self) -> None:
        decision, result = self.mediate(tool="read_code", target="src/app.py", scope="project-A", risk=None)
        self.assertEqual(decision.reason, "RISK_NOT_EXPLICIT")
        self.assertIsNone(result)

    def test_requested_scope_cannot_create_authorization(self) -> None:
        decision, result = self.mediate(tool="read_code", target="src/app.py", scope="project-B")
        self.assertEqual(decision.reason, "SCOPE_NOT_AUTHORIZED")
        self.assertIsNone(result)
        self.assertEqual(self.policy.authorized_scope, "project-A")

    def test_approval_is_attributable_and_single_use(self) -> None:
        approval = self.policy.issue_approval(actor="agent-001", tool="write_code", target="src/app.py", scope="project-A")
        first, result = self.mediate(tool="write_code", target="src/app.py", scope="project-A", approval=approval)
        replay, replay_result = self.mediate(tool="write_code", target="src/app.py", scope="project-A", approval=approval)
        altered, altered_result = self.mediate(tool="write_code", target="src/other.py", scope="project-A", approval=approval)
        self.assertEqual(first.outcome, "allow")
        self.assertIsNotNone(result)
        self.assertEqual(replay.reason, "APPROVAL_REPLAY")
        self.assertIsNone(replay_result)
        self.assertEqual(altered.reason, "APPROVAL_MISMATCH")
        self.assertIsNone(altered_result)

    def test_consumed_approval_remains_rejected_after_policy_restart(self) -> None:
        approval_store: dict[str, Approval] = {}
        first_policy = FakePolicyAuthority(
            allowed_tools={"write_code"}, authorized_scope="project-A", approval_store=approval_store
        )
        approval = first_policy.issue_approval(
            actor="agent-001", tool="write_code", target="src/app.py", scope="project-A"
        )
        first = first_policy.decide(
            actor="agent-001", tool="write_code", target="src/app.py", requested_scope="project-A", risk="high", approval=approval
        )

        restarted_policy = FakePolicyAuthority(
            allowed_tools={"write_code"}, authorized_scope="project-A", approval_store=approval_store
        )
        replay = restarted_policy.decide(
            actor="agent-001", tool="write_code", target="src/app.py", requested_scope="project-A", risk="high", approval=approval
        )

        self.assertEqual(first.outcome, "allow")
        self.assertEqual(replay.reason, "APPROVAL_REPLAY")

    def test_quota_pressure_stops_authorized_calls(self) -> None:
        quota = 2
        self.quota_limit = quota
        results: list[dict[str, str] | None] = []
        for _ in range(quota + 1):
            _decision, result = self.mediate(tool="read_code", target="src/app.py", scope="project-A")
            results.append(result)
        self.assertEqual(len([result for result in results if result is not None]), quota)
        self.assertEqual(len(self.herdr.calls), quota)
        blocked, blocked_result = self.mediate(tool="read_code", target="src/app.py", scope="project-A")
        self.assertEqual(blocked.reason, "QUOTA_EXCEEDED")
        self.assertIsNone(blocked_result)

    def test_quota_usage_remains_enforced_after_policy_restart(self) -> None:
        state: dict[str, int] = {}
        first_policy = FakeQuotaAuthority(limit=2, state=state)
        self.assertTrue(first_policy.consume())
        self.assertTrue(first_policy.consume())

        restarted_policy = FakeQuotaAuthority(limit=2, state=state)
        self.assertFalse(restarted_policy.consume())

    def test_forge_pass_must_match_exact_execution_attempt(self) -> None:
        decision, result = self.mediate(tool="write_code", target="src/app.py", scope="project-A")
        self.assertEqual(decision.outcome, "allow")
        assert result is not None
        self.assertFalse(self.forge.verify(attempt_id="attempt-001", result=result, reported_attempt_id="attempt-old", status="PASSED"))
        self.assertFalse(self.forge.verify(attempt_id="attempt-001", result=result, reported_attempt_id="attempt-001", status="FAILED"))
        self.assertTrue(self.forge.verify(attempt_id="attempt-001", result=result, reported_attempt_id="attempt-001", status="PASSED"))


if __name__ == "__main__":
    unittest.main()
