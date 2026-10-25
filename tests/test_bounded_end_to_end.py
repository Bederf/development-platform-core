import unittest

from adapters.forge_contract_adapter import ForgeContractAdapter, ForgeObservation
from adapters.forge_enrichment import ForgeSemanticEnrichment, StaticForgeEnrichmentProvider
from adapters.gateway_compatibility import project_execution_request, project_policy_decision


class BoundedEndToEndTests(unittest.TestCase):
    def test_authorized_execution_to_forge_candidate_flow(self):
        request = {"request_id": "r1", "session_id": "s1", "task_id": "t1", "capability": "verify", "arguments": {"path": "src"}, "arguments_sha256": "sha256:a", "authorization_id": "d1", "timeout_seconds": 30, "target": {"id": "repo"}, "baseline": {"id": "base"}, "capability_binding": {"id": "binding"}}
        decision = {"decision_id": "d1", "decision": "allow", "policy_id": "p", "policy_version": "1", "issued_at": "2026-01-01T00:00:00Z", "expires_at": "2027-01-01T00:00:00Z", "decision_digest": "sha256:d", "authority_binding": {"id": "authority"}}
        execution = project_execution_request(request, project_policy_decision(request, decision))
        observation = ForgeObservation("vat-1", "PASS", ({"name": "verify", "exit_code": 0},))
        enrichment = ForgeSemanticEnrichment(
            {"id": "actor.evaluator"}, {"id": "binding.evaluator"}, {"id": "profile.v1"}, {"id": "method.verify"},
            {"id": "subject.repo"}, {"id": "authority.evaluation"}, {"id": "request.x"},
            {"verification_attempt_id": "vat-1"}, {"source": "forge"}, {"state": "assessed"},
        )
        candidate = ForgeContractAdapter().evaluation_from_provider(observation, StaticForgeEnrichmentProvider(enrichment), {"verification_attempt_id": "vat-1"})
        self.assertFalse(execution["authoritative"])
        self.assertFalse(candidate["authoritative"])
        self.assertNotIn("acceptance", candidate)


if __name__ == "__main__":
    unittest.main()
