"""Cross-contract linkage checks for the Tool Mediation authority chain.

These tests validate existing Core schemas and the proposed crosswalk. They do
not add a new ExecutionEvidence contract or implement a production mediator.
"""

from __future__ import annotations

import unittest

from tests.test_contracts import validate


TIME = "2026-09-01T10:00:00Z"


def ref(semantic_type: str, identifier: str, *, immutable: bool = False) -> dict[str, str]:
    value = {"semantic_type": semantic_type, "id": identifier, "version": "1.0.0"}
    if immutable:
        value["digest"] = f"sha256:{identifier.replace('_', '-')}-digest"
    return value


def scope() -> dict:
    return {"scope_type": "project", "scope_id": "project-a", "profile": None}


def build_chain() -> dict[str, dict]:
    policy_request = {
        "schema": "policy-decision.v1",
        "entity_type": "policy_request",
        "request_id": "policy-request-001",
        "domain": "execution",
        "action": "write_code",
        "subject": ref("execution_proposal", "proposal-001", immutable=True),
        "actor": ref("agent", "agent-001"),
        "requested_by": ref("gsd_session", "session-001"),
        "policies": [ref("execution_policy", "policy-001")],
        "fact_inputs": [],
        "evaluation_inputs": [],
        "requested_scope": scope(),
        "requested_at": TIME,
        "lineage": [],
        "digest": "sha256:policy-request-digest",
    }
    policy_decision = {
        "schema": "policy-decision.v1",
        "entity_type": "policy_decision",
        "decision_id": "policy-decision-001",
        "request": ref("policy_request", "policy-request-001", immutable=True),
        "domain": "execution",
        "action": "write_code",
        "subject": ref("execution_proposal", "proposal-001", immutable=True),
        "actor": ref("agent", "agent-001"),
        "outcome": "allow",
        "policies": [ref("execution_policy", "policy-001")],
        "issuer": "fake-policy-authority",
        "authority_binding": ref("policy_authority", "authority-001"),
        "direct_supports": [ref("risk_assessment", "risk-001")],
        "reason_codes": ["authorized"],
        "conditions": [],
        "use_policy": {"mode": "single_use", "max_uses": 1},
        "validity_scope": scope(),
        "issued_at": TIME,
        "effective_from": TIME,
        "valid_until": "2026-09-01T11:00:00Z",
        "revoked_at": None,
        "lineage": [ref("policy_request", "policy-request-001", immutable=True)],
        "limitations": [],
        "limitations_availability": {"status": "assessed", "reason": None},
        "supersession": None,
        "digest": "sha256:policy-decision-digest",
    }
    constraints = {
        "working_scope": scope(),
        "filesystem_policy": ref("filesystem_policy", "fs-001", immutable=True),
        "network_policy": ref("network_policy", "net-001", immutable=True),
        "environment_policy": ref("environment_policy", "env-001", immutable=True),
        "timeout_seconds": 60,
    }
    proposal = {
        "schema": "engineering-execution.v1",
        "entity_type": "execution_proposal",
        "proposal_id": "proposal-001",
        "attempt_id": "attempt-001",
        "task_id": "task-001",
        "session_id": "session-001",
        "actor": ref("agent", "agent-001"),
        "capability_binding": ref("capability_binding", "code-write-001", immutable=True),
        "operation": "write_code",
        "arguments_contract": ref("arguments_contract", "code-write-args"),
        "arguments": {"path": "src/app.py"},
        "arguments_digest": "sha256:arguments-digest",
        "target": ref("repository", "repo-001", immutable=True),
        "baseline": ref("revision", "revision-001", immutable=True),
        "requested_constraints": constraints,
        "requested_by": ref("gsd_session", "session-001"),
        "requested_at": TIME,
        "validity_scope": scope(),
        "lineage": [],
        "digest": "sha256:proposal-digest",
    }
    authorized_request = {
        "schema": "engineering-execution.v1",
        "entity_type": "authorized_execution_request",
        "execution_request_id": "execution-request-001",
        "proposal": ref("execution_proposal", "proposal-001", immutable=True),
        "policy_decision": ref("policy_decision", "policy-decision-001", immutable=True),
        "policy_domain": "execution",
        "policy_action": "write_code",
        "authorization_use_id": "approval-use-001",
        "authorization_use_index": 1,
        "attempt_id": "attempt-001",
        "actor": ref("agent", "agent-001"),
        "capability_binding": ref("capability_binding", "code-write-001", immutable=True),
        "operation": "write_code",
        "arguments_contract": ref("arguments_contract", "code-write-args"),
        "arguments": {"path": "src/app.py"},
        "arguments_digest": "sha256:arguments-digest",
        "target": ref("repository", "repo-001", immutable=True),
        "baseline": ref("revision", "revision-001", immutable=True),
        "enforced_constraints": constraints,
        "executor_binding": ref("herdr_executor", "herdr-001", immutable=True),
        "issuer": "fake-tool-mediator",
        "authority_binding": ref("policy_authority", "authority-001"),
        "validity_scope": scope(),
        "issued_at": TIME,
        "expires_at": "2026-09-01T11:00:00Z",
        "lineage": [ref("execution_proposal", "proposal-001", immutable=True), ref("policy_decision", "policy-decision-001", immutable=True)],
        "digest": "sha256:authorized-request-digest",
    }
    execution_result = {
        "schema": "engineering-execution.v1",
        "entity_type": "execution_result",
        "execution_id": "execution-001",
        "execution_request": ref("authorized_execution_request", "execution-request-001", immutable=True),
        "proposal": ref("execution_proposal", "proposal-001", immutable=True),
        "policy_decision": ref("policy_decision", "policy-decision-001", immutable=True),
        "policy_domain": "execution",
        "policy_action": "write_code",
        "authorization_use_id": "approval-use-001",
        "attempt_id": "attempt-001",
        "actor": ref("agent", "agent-001"),
        "executor_binding": ref("herdr_executor", "herdr-001", immutable=True),
        "issuer": "fake-herdr-adapter",
        "authority_binding": ref("execution_authority", "execution-authority-001"),
        "capability_binding": ref("capability_binding", "code-write-001", immutable=True),
        "operation": "write_code",
        "target": ref("repository", "repo-001", immutable=True),
        "baseline": ref("revision", "revision-001", immutable=True),
        "arguments_digest": "sha256:arguments-digest",
        "operation_status": "completed",
        "attempted_effects": [{
            "effect_id": "effect-001",
            "effect_type": "file_write",
            "subject": ref("file", "src-app-py", immutable=True),
            "status": "completed",
            "reason_codes": [],
        }],
        "completed_effects": [{
            "effect_id": "effect-001",
            "effect_type": "file_write",
            "subject": ref("file", "src-app-py", immutable=True),
            "status": "completed",
            "reason_codes": [],
        }],
        "outputs": [],
        "artifacts": [ref("artifact", "artifact-001", immutable=True)],
        "observations": [ref("observation", "observation-001")],
        "failure_category": None,
        "reason_codes": [],
        "actual_environment": ref("environment", "environment-001"),
        "enforced_constraints": constraints,
        "started_at": TIME,
        "finished_at": "2026-09-01T10:01:00Z",
        "recorded_at": "2026-09-01T10:01:01Z",
        "validity_scope": scope(),
        "limitations": [],
        "limitations_availability": {"status": "assessed", "reason": None},
        "lineage": [ref("authorized_execution_request", "execution-request-001", immutable=True)],
        "supersession": None,
        "digest": "sha256:execution-result-digest",
    }
    verification = {
        "schema": "verification-result.v1",
        "request_id": "verification-request-001",
        "status": "PASSED",
        "checks": [{"check_id": "forge-check-001", "status": "PASSED", "command": "pytest", "evidence_ref": "observation-001"}],
        "evidence": ["observation-001"],
    }
    return {
        "policy_request": policy_request,
        "policy_decision": policy_decision,
        "proposal": proposal,
        "authorized_request": authorized_request,
        "execution_result": execution_result,
        "verification": verification,
    }


def assert_execution_linkage(chain: dict[str, dict]) -> None:
    """Apply the cross-contract linkage rules not expressible in schemas."""
    decision = chain["policy_decision"]
    authorized = chain["authorized_request"]
    result = chain["execution_result"]
    if decision["decision_id"] != authorized["policy_decision"]["id"]:
        raise AssertionError("authorized request references a different policy decision")
    if authorized["execution_request_id"] != result["execution_request"]["id"]:
        raise AssertionError("execution result references a different request")
    for field in ("attempt_id", "authorization_use_id", "arguments_digest", "baseline"):
        if authorized[field] != result[field]:
            raise AssertionError(f"execution result does not preserve authorized {field}")


class ToolMediationContractLinkageTests(unittest.TestCase):
    def test_existing_contracts_validate_individually(self) -> None:
        chain = build_chain()
        validate("policy-decision.v1.schema.json", chain["policy_request"])
        validate("policy-decision.v1.schema.json", chain["policy_decision"])
        validate("engineering-execution.v1.schema.json", chain["proposal"])
        validate("engineering-execution.v1.schema.json", chain["authorized_request"])
        validate("engineering-execution.v1.schema.json", chain["execution_result"])
        validate("verification-result.v1.schema.json", chain["verification"])

    def test_policy_and_execution_chain_reuses_existing_linkage(self) -> None:
        chain = build_chain()
        assert_execution_linkage(chain)
        self.assertEqual(chain["policy_decision"]["decision_id"], chain["authorized_request"]["policy_decision"]["id"])
        self.assertEqual(chain["authorized_request"]["execution_request_id"], chain["execution_result"]["execution_request"]["id"])
        self.assertEqual(chain["authorized_request"]["attempt_id"], chain["execution_result"]["attempt_id"])
        self.assertEqual(chain["authorized_request"]["authorization_use_id"], chain["execution_result"]["authorization_use_id"])
        self.assertEqual(chain["authorized_request"]["arguments_digest"], chain["execution_result"]["arguments_digest"])
        self.assertEqual(chain["authorized_request"]["baseline"], chain["execution_result"]["baseline"])

    def test_mismatched_policy_decision_is_rejected_by_linkage_rule(self) -> None:
        chain = build_chain()
        chain["authorized_request"]["policy_decision"]["id"] = "policy-decision-other"
        with self.assertRaisesRegex(AssertionError, "policy decision"):
            assert_execution_linkage(chain)

    def test_mismatched_attempt_or_approval_use_is_rejected(self) -> None:
        for field in ("attempt_id", "authorization_use_id"):
            chain = build_chain()
            chain["execution_result"][field] = f"{chain['execution_result'][field]}-other"
            with self.subTest(field=field), self.assertRaisesRegex(AssertionError, field):
                assert_execution_linkage(chain)

    def test_mismatched_baseline_is_rejected(self) -> None:
        chain = build_chain()
        chain["execution_result"]["baseline"]["id"] = "revision-other"
        with self.assertRaisesRegex(AssertionError, "baseline"):
            assert_execution_linkage(chain)

    def test_verification_result_exposes_a_current_linkage_gap(self) -> None:
        verification = build_chain()["verification"]
        self.assertNotIn("execution_id", verification)
        self.assertNotIn("attempt_id", verification)
        self.assertNotIn("baseline", verification)
        self.assertEqual(verification["status"], "PASSED")

    def test_executor_success_is_not_forge_success(self) -> None:
        chain = build_chain()
        execution = chain["execution_result"]
        verification = chain["verification"]
        self.assertEqual(execution["operation_status"], "completed")
        self.assertEqual(verification["status"], "PASSED")
        self.assertNotEqual(execution["operation_status"], verification["status"])


if __name__ == "__main__":
    unittest.main()
