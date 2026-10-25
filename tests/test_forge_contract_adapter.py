import unittest

from adapters.forge_contract_adapter import ForgeContractAdapter, ForgeMappingError, ForgeObservation
from adapters.forge_enrichment import StaticForgeEnrichmentProvider


class ForgeContractAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = ForgeContractAdapter()
        self.observation = ForgeObservation("vat-1", "PASS", ({"name": "tests", "exit_code": 0},))
        self.enrichment = {
            "request": "evaluation-request-ref", "definition": "definition-ref", "profile": "profile-ref",
            "subject": "subject-ref", "evaluator_actor": "evaluator-ref", "evaluator_binding": "binding-ref",
            "method": "method-ref", "authority_binding": "authority-ref",
        }

    def test_pass_requires_semantic_enrichment_and_remains_candidate(self):
        result = self.adapter.evaluation_candidate(self.observation, self.enrichment)
        self.assertFalse(result["authoritative"])
        self.assertEqual(result["provider_status"], "PASS")

    def test_pass_without_checks_is_rejected(self):
        with self.assertRaisesRegex(ForgeMappingError, "without check"):
            self.adapter.evaluation_candidate(ForgeObservation("vat-1", "PASS", ()), self.enrichment)

    def test_missing_semantic_material_is_rejected(self):
        with self.assertRaisesRegex(ForgeMappingError, "evaluator_actor"):
            self.adapter.evaluation_candidate(self.observation, {"request": "ref"})

    def test_evidence_requires_provenance_and_is_not_a_record(self):
        evaluation = self.adapter.evaluation_candidate(self.observation, self.enrichment)
        evidence = self.adapter.evidence_candidate(
            self.observation, evaluation,
            {"subject": "subject-ref", "producer": "forge", "submitted_by": "forge", "collection_method": "check"},
        )
        self.assertFalse(evidence["authoritative"])
        self.assertEqual(evidence["candidate_type"], "evidence_submission")

    def test_evidence_cannot_be_created_from_authoritative_input(self):
        with self.assertRaisesRegex(ForgeMappingError, "non-authoritative"):
            self.adapter.evidence_candidate(self.observation, {"candidate_type": "evaluation_result", "authoritative": True}, {})

    def test_provider_enrichment_composes_without_authority(self):
        e = {"evaluator_actor": {"id": "actor"}, "evaluator_binding": {"id": "binding"}, "evaluation_profile": {"id": "profile"}, "evaluation_method": {"id": "method"}, "subject": {"id": "subject"}, "authority_binding": {"id": "authority"}, "request": {"id": "request"}, "correlation": {"verification_attempt_id": "vat-1"}, "provenance": {"source": "forge"}, "availability": {"state": "assessed"}}
        e["failure"] = None
        result = self.adapter.evaluation_from_provider(self.observation, StaticForgeEnrichmentProvider(type("E", (), e)()), {"verification_attempt_id": "vat-1"})
        self.assertFalse(result["authoritative"])


if __name__ == "__main__":
    unittest.main()
