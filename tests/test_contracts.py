import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).parents[1]
CONTRACTS = ROOT / "contracts"


def validate(name: str, instance: dict) -> None:
    schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    registry = Registry()
    for path in CONTRACTS.glob("*.schema.json"):
        resource = Resource.from_contents(json.loads(path.read_text(encoding="utf-8")))
        registry = registry.with_resource(path.name, resource)
        if resource.contents.get("$id"):
            registry = registry.with_resource(resource.contents["$id"], resource)
    Draft202012Validator(schema, registry=registry).validate(instance)


def intelligence(status: str, trusted: bool) -> dict:
    return {
        "schema": "repository-intelligence.v1",
        "status": status,
        "provider": "fake-graph",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "indexed_revision": "abc123",
        "trusted": trusted,
        "relevant_files": [],
        "relevant_symbols": [],
        "notes": [],
        "freshness_evidence": [],
    }


def disabled_session_brief() -> dict:
    return {"status": "unavailable", "path": None, "reason": "disabled by fake fixture"}


def disabled_runtime_history() -> dict:
    return {"status": "unavailable", "recent_runs": [], "reason": "disabled by fake fixture"}


class ContractConformanceTests(unittest.TestCase):
    def test_all_public_contracts_have_versioned_ids(self) -> None:
        schemas = sorted(CONTRACTS.glob("*.schema.json"))
        self.assertGreaterEqual(len(schemas), 10)
        for path in schemas:
            schema = json.loads(path.read_text(encoding="utf-8"))
            # Candidate-only artifacts are validated by their own lifecycle
            # evidence; they are not promoted public contracts. Promoted and
            # public contracts may advance beyond v1, but must retain an
            # explicit major version in the identity.
            if schema.get("x-status") == "candidate-only":
                continue
            self.assertRegex(schema["$id"], r"\.v[0-9]+(?:\.candidate)?$")

    def test_repository_intelligence_states_are_explicit(self) -> None:
        for status, trusted in (("CURRENT", True), ("REFRESHED", True), ("DEGRADED", False), ("UNAVAILABLE", False)):
            validate("repository-intelligence.v1.schema.json", intelligence(status, trusted))

    def test_capability_selection_accepts_explicit_prerelease_identity(self) -> None:
        validate("capability-selection.v1.schema.json", {
            "schema": "development-capability-selection.v1",
            "project_id": "preview-consumer",
            "capabilities": {
                "gsd": {
                    "enabled": True,
                    "implementation": "gsd.master",
                    "version": "3.4.0-preview.1",
                }
            },
        })

    def test_fake_startup_context_composes_repository_intelligence(self) -> None:
        context = {
            "schema": "agent-startup-context.v1",
            "project_id": "rewards-os",
            "repository_root": "/workspace/rewards-os",
            "knowledge_root": "vault/",
            "planning_root": "vault/00-GSD-Phases/",
            "current_objective": "define platform contracts",
            "active_phase": "001",
            "session": {"session_id": "fake-session-001", "governance_reference": None},
            "repository_intelligence": intelligence("CURRENT", True),
            "agents": {"claude": True, "codex": True, "opencode": True},
            "session_brief": disabled_session_brief(),
            "runtime_history": disabled_runtime_history(),
        }
        validate("agent-startup-context.v1.schema.json", context)

    def test_fake_agent_adapter_preserves_startup_context(self) -> None:
        request = {
            "schema": "agent-adapter.v1",
            "agent": "claude",
            "request_id": "adapter-request-001",
            "startup_context": {
                "schema": "agent-startup-context.v1",
                "project_id": "rewards-os",
                "repository_root": "/workspace/rewards-os",
                "knowledge_root": "vault/",
                "planning_root": "vault/00-GSD-Phases/",
                "current_objective": None,
                "active_phase": None,
                "session": {"session_id": "fake-session-002"},
                "repository_intelligence": intelligence("UNAVAILABLE", False),
                "agents": {"claude": True},
                "session_brief": disabled_session_brief(),
                "runtime_history": disabled_runtime_history(),
            },
            "mode": "read_only",
            "task_manifest": None,
        }
        validate("agent-adapter.v1.schema.json", request)
        self.assertEqual(request["startup_context"]["project_id"], "rewards-os")

    def test_fake_forge_result_is_typed_and_correlated(self) -> None:
        validate("forge-adapter.v1.schema.json", {
            "schema": "forge-adapter.v1",
            "operation": "verify",
            "project_id": "rewards-os",
            "request_id": "forge-request-001",
            "session_id": "forge-session-001",
            "verification_request": {"checks": ["contract-tests"]},
            "closeout_context": None,
        })
        validate("verification-result.v1.schema.json", {
            "schema": "verification-result.v1",
            "request_id": "forge-request-001",
            "status": "PASSED",
            "checks": [{"check_id": "contract-tests", "status": "PASSED", "command": "python -m unittest", "evidence_ref": "stdout"}],
            "evidence": ["stdout"],
        })

    def test_fake_gsd_lifecycle_has_versioned_events(self) -> None:
        validate("gsd-planning-lifecycle.v1.schema.json", {
            "schema": "gsd-planning-lifecycle.v1",
            "phase_id": "001",
            "phase_status": "AUTHORIZED",
            "lifecycle_events": [{
                "event": "STARTED",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "evidence_ref": "phase-001",
            }],
        })

    def test_fake_gsd_session_governance_requires_explicit_intent_and_profile(self) -> None:
        validate("gsd-session-governance.v1.schema.json", {
            "schema": "gsd-session-governance.v1",
            "session_id": "session-001",
            "lifecycle_state": "PROFILE_ASSESSED",
            "intent_status": "CAPTURED",
            "objective": "define platform contracts",
            "profile": {
                "name": "medium",
                "execution_mode": "STANDARD",
                "source": "engine",
            },
            "lifecycle_events": [],
        })

    def test_fake_humanizer_capability_delegates_verification_to_forge(self) -> None:
        validate("code-humanizer.v1.schema.json", {
            "schema": "code-humanizer.v1",
            "capability": "code-humanizer",
            "version": "0.4.1",
            "request_id": "humanizer-request-001",
            "action": {
                "capability": "code-humanizer",
                "target": "src/service.py",
                "profile": "team-default",
                "aggression": 0.6,
            },
            "acceptance": {
                "semantic_integrity": "required",
                "lint": "required",
                "tests": "required",
                "forge_verification": "required",
            },
            "artifact": {
                "candidate_artifact": {"path": "src/service.py", "content_hash": "sha256:candidate"},
                "source_hash": "sha256:source",
                "candidate_hash": "sha256:candidate",
                "transformation_manifest": {
                    "type": "artifact",
                    "ref": "artifacts/humanizer-request-001/manifest.json",
                },
            },
            "verification": {
                "delegated_to": "forge",
                "required_checks": ["semantic_integrity", "lint", "tests"],
                "verification_request_ref": "forge-request-001",
            },
        })

    def test_agent_operating_contract_and_behavior_profile_are_versioned(self) -> None:
        behavior_profile = {
            "schema": "behavior-profile.v1",
            "profile_id": "default",
            "version": "1.0.0",
            "total_points": 100,
            "elements": [
                {"name": "fire", "points": 20, "characteristics": ["initiative", "decisiveness", "confidence", "momentum", "challenge"]},
                {"name": "air", "points": 20, "characteristics": ["analysis", "curiosity", "communication", "creativity", "exploration"]},
                {"name": "earth", "points": 20, "characteristics": ["discipline", "reliability", "precision", "stability", "process"]},
                {"name": "water", "points": 20, "characteristics": ["empathy", "collaboration", "patience", "adaptability", "listening"]},
                {"name": "ether", "points": 20, "characteristics": ["purpose", "wisdom", "reflection", "integration", "long-term-thinking"]},
            ],
            "change_record": None,
        }
        validate("behavior-profile.v1.schema.json", behavior_profile)
        contract = {
            "schema": "agent-operating-contract.v1",
            "contract_id": "example-agent",
            "version": "1.0.0",
            "identity": {"agent_id": "example-agent", "name": "Example Agent"},
            "intent": {"business": "Improve an outcome", "operational": "Perform a governed task", "system": "Use approved evidence and tools"},
            "authority": {"read": ["approved-source"], "recommend": ["approved-action"], "execute": [], "approval_required": True},
            "policies": ["fail-closed"],
            "evidence_requirements": {"sources": ["approved-source"], "minimum_sources": 1, "freshness": "task-defined"},
            "quality_thresholds": {"minimum_confidence": 0.8, "minimum_evidence_quality": 0.8},
            "success_criteria": ["Produce an auditable result"],
            "interfaces": ["tool-broker"],
            "behavior_profile": behavior_profile,
            "learning_rules": ["Record outcome before proposing change"],
        }
        validate("agent-operating-contract.v1.schema.json", contract)


if __name__ == "__main__":
    unittest.main()
