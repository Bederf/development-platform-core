"""Fake-provider conformance for the provider-neutral development workflow."""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from tests.test_contracts import validate


ROOT = Path(__file__).parents[1]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeWorkflowProvider:
    """Deterministic in-memory provider; it has no repository side effects."""

    def __init__(self) -> None:
        timestamp = now()
        self.workflow = {
            "schema": "development-workflow.v1",
            "workflow_id": "workflow-fake-001",
            "intent_ref": "intent-001",
            "status": "ACTIVE",
            "current_stage": "INTENT",
            "artifacts": [self._artifact("intent-001", "intent", "INTENT", "fake-intent")],
            "gates": [],
            "transitions": [],
            "verification_refs": [],
            "evidence_refs": ["evidence-intent-001"],
            "acceptance_ref": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        self.provider_id = "fake-workflow-provider"

    def _artifact(self, ref: str, kind: str, stage: str, producer: str) -> dict[str, object]:
        return {
            "artifact_ref": ref,
            "kind": kind,
            "stage": stage,
            "artifact_version": "1.0.0",
            "digest": f"sha256:{ref}",
            "producer": producer,
            "supersedes_ref": None,
            "created_at": now(),
        }

    def _save(self) -> dict[str, object]:
        self.workflow["updated_at"] = now()
        validate("development-workflow.v1.schema.json", self.workflow)
        return copy.deepcopy(self.workflow)

    def approve(self, stage: str, gate_id: str) -> dict[str, object]:
        self.workflow["gates"].append({
            "gate_id": gate_id,
            "stage": stage,
            "decision": "APPROVED",
            "decided_by": "operator-gate",
            "evidence_refs": [f"evidence-{gate_id}"],
            "decided_at": now(),
        })
        return self._save()

    def advance(self, stage: str, artifact_kind: str, artifact_ref: str, *, gate_id: str | None = None) -> dict[str, object]:
        if gate_id and not any(g["gate_id"] == gate_id and g["decision"] == "APPROVED" for g in self.workflow["gates"]):
            self.workflow["status"] = "BLOCKED"
            return self._save()
        previous = self.workflow["current_stage"]
        self.workflow["artifacts"].append(self._artifact(artifact_ref, artifact_kind, stage, self.provider_id))
        self.workflow["transitions"].append({
            "transition_id": f"transition-{len(self.workflow['transitions']) + 1}",
            "from_stage": previous,
            "to_stage": stage,
            "actor": self.provider_id,
            "decision": "ADVANCE",
            "evidence_refs": [f"evidence-{artifact_ref}"],
            "occurred_at": now(),
        })
        self.workflow["current_stage"] = stage
        self.workflow["evidence_refs"].append(f"evidence-{artifact_ref}")
        return self._save()

    def verify(self, outcome: str, *, verifier: str = "independent-verifier") -> dict[str, object]:
        ref = f"verification-{len(self.workflow['verification_refs']) + 1}"
        self.workflow["artifacts"].append(self._artifact(ref, "verification", "VERIFICATION", verifier))
        self.workflow["verification_refs"].append(ref)
        self.workflow["evidence_refs"].append(f"evidence-{ref}")
        if outcome == "FAIL":
            self.workflow["status"] = "BLOCKED"
        return self._save()

    def converge(self, *, requirements_complete: bool) -> dict[str, object]:
        if not requirements_complete:
            self.workflow["status"] = "ACTIVE"
            return self.advance("REMEDIATION", "remediation", "remediation-001")
        return self.advance("CONVERGENCE", "convergence", "convergence-001", gate_id="gate-convergence")

    def accept(self) -> dict[str, object]:
        verification_artifacts = [
            item for item in self.workflow["artifacts"] if item["kind"] == "verification"
        ]
        has_independent_verification = any(
            item["producer"] != self.provider_id for item in verification_artifacts
        )
        has_convergence = any(item["kind"] == "convergence" for item in self.workflow["artifacts"])
        has_acceptance_gate = any(
            gate["stage"] == "ACCEPTANCE"
            and gate["decision"] == "APPROVED"
            for gate in self.workflow["gates"]
        )
        if (
            self.workflow["status"] != "ACTIVE"
            or not self.workflow["verification_refs"]
            or not has_independent_verification
            or not has_convergence
            or not has_acceptance_gate
        ):
            self.workflow["status"] = "BLOCKED"
            return self._save()
        self.workflow["acceptance_ref"] = "acceptance-001"
        self.workflow["artifacts"].append(self._artifact("acceptance-001", "acceptance", "ACCEPTANCE", "acceptance-authority"))
        self.workflow["authorization_ref"] = "fake-authorization-001"
        self.workflow["authorization_digest"] = "sha256:" + "1" * 64
        self.workflow["acceptance_content"] = {
            "schema": "acceptance-content.v1",
            "acceptance_ref": "acceptance-001",
            "artifact_ref": "acceptance-001",
            "kind": "acceptance",
            "stage": "ACCEPTANCE",
            "artifact_version": "1.0.0",
            "producer": "acceptance-authority",
            "supersedes_ref": None,
            "created_at": now(),
            "phase_specification": {
                "phase_id": "fake-phase-001",
                "specification_ref": "fake-specification-001",
                "specification_id": "fake-specification-001",
                "specification_version": "1.0.0",
                "specification_hash": "sha256:" + "2" * 64,
                "forge_required": False,
                "verification_mode": "qualification",
            },
            "authorization_ref": "fake-authorization-001",
            "authorization_digest": "sha256:" + "1" * 64,
            "review_request_ref": "fake-review-request-001",
            "implementation_revision_ref": "implementation-001",
            "forge_evidence_ref": "not-applicable",
            "forge_evidence_digest": None,
            "convergence_refs": ["convergence-001"],
            "authority_boundary": {
                "forge_non_authoritative": True,
                "production_authority_granted": False,
            },
        }
        self.workflow["current_stage"] = "ACCEPTANCE"
        self.workflow["status"] = "ACCEPTED"
        return self._save()

    def reject(self) -> dict[str, object]:
        self.workflow["status"] = "REJECTED"
        return self._save()


class DevelopmentWorkflowConformanceTests(unittest.TestCase):
    EXECUTED_CASES = {
        "complete-independent-verification",
        "missing-gate-blocks-advance",
        "verification-failure-requires-remediation",
        "verification-unavailable-requires-remediation",
        "convergence-finds-traceability-gap",
        "rejected-work-preserves-history",
        "provider-cannot-self-certify",
        "unsupported-version-fails-closed",
        "artifact-revision-lineage",
    }

    @classmethod
    def setUpClass(cls) -> None:
        fixture = yaml.safe_load((ROOT / "fixtures/conformance/development-workflow-v1.yaml").read_text(encoding="utf-8"))
        cls.cases = {case["id"]: case["expected"] for case in fixture["cases"]}
        cls.schema = json.loads((ROOT / "contracts/development-workflow.v1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)

    def test_fixture_is_versioned_and_complete(self) -> None:
        self.assertEqual(self.cases["complete-independent-verification"], "ACCEPTED")
        self.assertEqual(set(self.cases), self.EXECUTED_CASES)

    def test_complete_flow_requires_gate_and_independent_verification(self) -> None:
        provider = FakeWorkflowProvider()
        for stage, kind, ref, gate in (
            ("SPECIFICATION", "specification", "spec-001", "gate-specification"),
            ("ASSESSMENT", "assessment", "assessment-001", "gate-assessment"),
            ("PLAN", "plan", "plan-001", "gate-plan"),
            ("TASKS", "task_list", "tasks-001", "gate-tasks"),
        ):
            provider.approve(stage, gate)
            provider.advance(stage, kind, ref, gate_id=gate)
        provider.advance("IMPLEMENTATION", "implementation", "implementation-001")
        provider.approve("VERIFICATION", "gate-verification")
        provider.verify("PASS")
        provider.approve("CONVERGENCE", "gate-convergence")
        provider.converge(requirements_complete=True)
        provider.approve("ACCEPTANCE", "gate-acceptance")
        result = provider.accept()
        self.assertEqual(result["status"], self.cases["complete-independent-verification"])
        self.assertNotEqual(provider.provider_id, "independent-verifier")
        self.assertEqual(result["current_stage"], "ACCEPTANCE")

    def test_missing_gate_blocks_advance(self) -> None:
        result = FakeWorkflowProvider().advance("SPECIFICATION", "specification", "spec-001", gate_id="gate-specification")
        self.assertEqual(result["status"], self.cases["missing-gate-blocks-advance"])
        self.assertEqual(result["current_stage"], "INTENT")

    def test_failed_verification_requires_remediation(self) -> None:
        provider = FakeWorkflowProvider()
        provider.verify("FAIL")
        result = provider.converge(requirements_complete=False)
        self.assertEqual(result["current_stage"], "REMEDIATION")
        self.assertEqual(result["current_stage"], self.cases["verification-failure-requires-remediation"])
        self.assertEqual(result["status"], "ACTIVE")

    def test_unavailable_verification_requires_remediation(self) -> None:
        provider = FakeWorkflowProvider()
        provider.verify("UNAVAILABLE")
        self.assertEqual(provider.workflow["status"], "ACTIVE")
        result = provider.converge(requirements_complete=False)
        self.assertEqual(result["current_stage"], self.cases["verification-unavailable-requires-remediation"])
        self.assertEqual(result["status"], "ACTIVE")

    def test_convergence_traceability_gap_preserves_prior_artifacts(self) -> None:
        provider = FakeWorkflowProvider()
        before = provider._save()
        result = provider.converge(requirements_complete=False)
        self.assertEqual(result["current_stage"], self.cases["convergence-finds-traceability-gap"])
        self.assertTrue(any(item["artifact_ref"] == "intent-001" for item in result["artifacts"]))
        self.assertGreater(len(result["artifacts"]), len(before["artifacts"]))

    def test_rejection_preserves_history(self) -> None:
        provider = FakeWorkflowProvider()
        before = provider._save()
        result = provider.reject()
        self.assertEqual(result["status"], self.cases["rejected-work-preserves-history"])
        self.assertEqual(result["artifacts"], before["artifacts"])
        self.assertEqual(result["evidence_refs"], before["evidence_refs"])

    def test_provider_cannot_self_certify_acceptance(self) -> None:
        provider = FakeWorkflowProvider()
        provider.workflow["status"] = "ACTIVE"
        provider.workflow["current_stage"] = "CONVERGENCE"
        provider.workflow["verification_refs"] = ["fake-verification"]
        provider.workflow["artifacts"].append(
            provider._artifact("fake-verification", "verification", "VERIFICATION", provider.provider_id)
        )
        result = provider.accept()
        self.assertEqual(result["status"], self.cases["provider-cannot-self-certify"])
        self.assertIsNone(result["acceptance_ref"])

    def test_acceptance_requires_an_explicit_acceptance_gate(self) -> None:
        provider = FakeWorkflowProvider()
        provider.workflow["current_stage"] = "CONVERGENCE"
        provider.workflow["artifacts"].append(
            provider._artifact("verification-001", "verification", "VERIFICATION", "independent-verifier")
        )
        provider.workflow["verification_refs"] = ["verification-001"]
        provider.workflow["artifacts"].append(
            provider._artifact("convergence-001", "convergence", "CONVERGENCE", provider.provider_id)
        )
        result = provider.accept()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["acceptance_ref"])

    def test_unsupported_contract_version_fails_closed(self) -> None:
        provider = FakeWorkflowProvider()
        provider.workflow["schema"] = "development-workflow.v2"
        self.assertEqual(self.cases["unsupported-version-fails-closed"], "FAIL_CLOSED")
        with self.assertRaises(Exception):
            provider._save()

    def test_artifact_revision_is_explicit(self) -> None:
        provider = FakeWorkflowProvider()
        provider.advance("SPECIFICATION", "specification", "spec-001")
        replacement = provider._artifact("spec-002", "specification", "SPECIFICATION", provider.provider_id)
        replacement["supersedes_ref"] = "spec-001"
        provider.workflow["artifacts"].append(replacement)
        result = provider._save()
        original_refs = {item["artifact_ref"] for item in result["artifacts"]}
        self.assertIn("spec-001", original_refs)
        self.assertIn("spec-002", original_refs)
        self.assertEqual(next(item for item in result["artifacts"] if item["artifact_ref"] == "spec-002")["supersedes_ref"], "spec-001")
        self.assertEqual(replacement["supersedes_ref"], "spec-001")
        self.assertEqual(replacement["artifact_version"], "1.0.0")
        self.assertEqual(self.cases["artifact-revision-lineage"], "EXPLICIT")


if __name__ == "__main__":
    unittest.main()
