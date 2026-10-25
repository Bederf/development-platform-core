import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).parents[1]
SCHEMA = json.loads(
    (ROOT / "contracts/multi-instance-provider.v1.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA)


def validate(payload: dict) -> None:
    VALIDATOR.validate(payload)


def topology_request() -> dict:
    def instance(instance_id: str, isolation_key: str, role: str, mode: str) -> dict:
        return {
            "instance_id": instance_id,
            "isolation_key": isolation_key,
            "role": role,
            "deployment_mode": mode,
            "credential_ref": f"vault://credentials/{instance_id}",
            "configuration_ref": f"config://instances/{instance_id}",
            "state_ref": f"state://instances/{instance_id}",
            "log_ref": f"log://instances/{instance_id}",
            "failure_domain": f"process-{instance_id}",
            "admission_policy": {"mode": "ALLOWLIST", "principal_ids": []},
            "authorization_ref": "authority://memberships",
            "health_policy": {
                "interval_seconds": 60,
                "probe_ref": f"probe://instances/{instance_id}",
            },
        }

    return {
        "schema": "multi-instance-provider.v1",
        "message_type": "request",
        "operation": "configure_topology",
        "request_id": "topology-001",
        "scope_id": "customer-messaging",
        "topology": {
            "revision": 7,
            "instances": [
                instance("legacy-operator", "tenant-a", "operator", "LEGACY_SHARED"),
                instance("tenant-b-operator", "tenant-b", "operator", "DEDICATED"),
                instance("tenant-b-worker", "tenant-b", "worker", "DEDICATED"),
            ],
        },
    }


class FakeMembershipProvider:
    """Test-only provider proving contract behavior before implementation extraction."""

    def __init__(self) -> None:
        self.outer: set[tuple[str, str, str]] = set()
        self.inner: set[tuple[str, str, str]] = set()
        self.fail_inner = False

    def change(self, request: dict) -> dict:
        validate(request)
        change = request["membership_change"]
        key = (change["principal_id"], change["isolation_key"], change["role"])
        add = change["action"] == "ADD"
        before_outer = set(self.outer)
        before_inner = set(self.inner)
        try:
            (self.outer.add if add else self.outer.discard)(key)
            if self.fail_inner:
                raise RuntimeError("fake inner authority unavailable")
            (self.inner.add if add else self.inner.discard)(key)
        except RuntimeError as exc:
            self.outer = before_outer
            self.inner = before_inner
            result = {
                "schema": "multi-instance-provider.v1",
                "message_type": "result",
                "operation": "change_membership",
                "request_id": "result-" + request["request_id"],
                "in_reply_to": request["request_id"],
                "scope_id": request["scope_id"],
                "outcome": {"status": "FAILED"},
                "transaction": {
                    "atomic": True,
                    "committed": False,
                    "rolled_back": True,
                    "outer_admission": "ROLLED_BACK",
                    "inner_authorization": "FAILED",
                },
                "error": {"code": "INNER_UPDATE_FAILED", "message": str(exc), "retryable": True},
            }
        else:
            result = {
                "schema": "multi-instance-provider.v1",
                "message_type": "result",
                "operation": "change_membership",
                "request_id": "result-" + request["request_id"],
                "in_reply_to": request["request_id"],
                "scope_id": request["scope_id"],
                "outcome": {"status": "APPLIED", "revision": 8},
                "transaction": {
                    "atomic": True,
                    "committed": True,
                    "rolled_back": False,
                    "outer_admission": "APPLIED",
                    "inner_authorization": "APPLIED",
                },
            }
        validate(result)
        return result


def membership_request() -> dict:
    return {
        "schema": "multi-instance-provider.v1",
        "message_type": "request",
        "operation": "change_membership",
        "request_id": "membership-001",
        "scope_id": "customer-messaging",
        "membership_change": {
            "principal_id": "principal-42",
            "isolation_key": "tenant-b",
            "role": "operator",
            "action": "ADD",
            "targets": ["OUTER_ADMISSION", "INNER_AUTHORIZATION"],
            "consistency": "REQUIRED_ATOMIC",
            "expected_revision": 7,
            "requested_by": "principal-manager",
        },
    }


class MultiInstanceProviderContractTests(unittest.TestCase):
    def test_topology_supports_dedicated_instances_and_legacy_coexistence(self) -> None:
        request = topology_request()
        validate(request)
        modes = {item["deployment_mode"] for item in request["topology"]["instances"]}
        self.assertEqual(modes, {"DEDICATED", "LEGACY_SHARED"})

    def test_contract_accepts_only_opaque_credential_references(self) -> None:
        request = topology_request()
        instance = request["topology"]["instances"][0]
        instance["token"] = "plaintext-secret"
        with self.assertRaises(ValidationError):
            validate(request)

        request = topology_request()
        request["topology"]["instances"][0]["credential_ref"] = "plaintext-secret"
        with self.assertRaises(ValidationError):
            validate(request)

    def test_fake_provider_updates_outer_and_inner_gates_atomically(self) -> None:
        provider = FakeMembershipProvider()
        request = membership_request()
        result = provider.change(request)
        key = ("principal-42", "tenant-b", "operator")
        self.assertIn(key, provider.outer)
        self.assertIn(key, provider.inner)
        self.assertTrue(result["transaction"]["committed"])

    def test_fake_provider_rolls_back_outer_gate_when_inner_gate_fails(self) -> None:
        provider = FakeMembershipProvider()
        provider.fail_inner = True
        result = provider.change(membership_request())
        self.assertEqual(provider.outer, set())
        self.assertEqual(provider.inner, set())
        self.assertEqual(result["outcome"]["status"], "FAILED")
        self.assertTrue(result["transaction"]["rolled_back"])

    def test_health_is_reported_per_failure_domain(self) -> None:
        checked_at = datetime.now(timezone.utc).isoformat()
        result = {
            "schema": "multi-instance-provider.v1",
            "message_type": "result",
            "operation": "report_health",
            "request_id": "health-result-001",
            "in_reply_to": "health-request-001",
            "scope_id": "customer-messaging",
            "outcome": {"status": "APPLIED"},
            "health": [
                {
                    "instance_id": "tenant-a-operator",
                    "failure_domain": "process-tenant-a-operator",
                    "status": "HEALTHY",
                    "checked_at": checked_at,
                },
                {
                    "instance_id": "tenant-b-operator",
                    "failure_domain": "process-tenant-b-operator",
                    "status": "UNHEALTHY",
                    "checked_at": checked_at,
                },
            ],
        }
        validate(result)
        self.assertEqual(result["health"][0]["status"], "HEALTHY")
        self.assertEqual(result["health"][1]["status"], "UNHEALTHY")

    def test_rotation_is_scoped_to_one_instance(self) -> None:
        request = {
            "schema": "multi-instance-provider.v1",
            "message_type": "request",
            "operation": "rotate_credential",
            "request_id": "rotation-001",
            "scope_id": "customer-messaging",
            "credential_rotation": {
                "instance_id": "tenant-b-operator",
                "current_credential_ref": "vault://credentials/tenant-b-operator/v1",
                "replacement_credential_ref": "vault://credentials/tenant-b-operator/v2",
                "restart_scope": "TARGET_INSTANCE_ONLY",
            },
        }
        validate(request)


if __name__ == "__main__":
    unittest.main()
