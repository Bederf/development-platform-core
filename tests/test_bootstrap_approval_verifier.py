import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from adapters.radix.approval import BootstrapApprovalError, plan_digest, verify_approval


ROOT = Path(__file__).parents[1]


class BootstrapApprovalVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((ROOT / "contracts/bootstrap-approval.v1.schema.json").read_text(encoding="utf-8"))

    def plan(self) -> dict:
        return {
            "schema": "radix-guided-bootstrap-plan.v1",
            "plan_id": "radix-guided-bootstrap",
            "project_id": "fixture-project",
            "repository_root": "/workspace/fixture",
            "selections": [],
            "generated_artifacts": ["development-platform.yaml", ".development-platform/capabilities.yaml"],
            "limitations": ["one", "two", "three"],
        }

    def approval(self, plan: dict) -> dict:
        return {
            "schema": "bootstrap-approval.v1",
            "entity_type": "bootstrap_approval",
            "approval_id": "approval.fixture.001",
            "subject": {
                "semantic_type": "bootstrap_plan",
                "id": plan["plan_id"],
                "version": "1.0.0",
                "digest": plan_digest(plan),
                "project_id": plan["project_id"],
            },
            "decision": "approved",
            "issuer": "fixture.operator",
            "authority_binding": {"semantic_type": "approval_authority", "id": "authority.fixture", "version": "1.0.0"},
            "scope": {"scope_type": "project", "scope_id": plan["project_id"]},
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "reason_codes": ["operator_reviewed_plan"],
        }

    def test_fake_provider_approval_matches_exact_plan(self) -> None:
        plan = self.plan()
        verify_approval(plan=plan, approval=self.approval(plan), schema=self.schema)

    def test_digest_mismatch_and_expiry_fail_closed(self) -> None:
        plan = self.plan()
        approval = self.approval(plan)
        changed = copy.deepcopy(plan)
        changed["project_id"] = "other-project"
        with self.assertRaisesRegex(BootstrapApprovalError, "project_id"):
            verify_approval(plan=changed, approval=approval, schema=self.schema)
        expired = self.approval(plan)
        expired["valid_until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(BootstrapApprovalError, "expired"):
            verify_approval(plan=plan, approval=expired, schema=self.schema)


if __name__ == "__main__":
    unittest.main()
