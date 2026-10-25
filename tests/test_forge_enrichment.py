import unittest

from adapters.forge_enrichment import EnrichmentError, ForgeSemanticEnrichment, StaticForgeEnrichmentProvider


def enrichment(state="assessed", failure=None):
    return ForgeSemanticEnrichment(
        {"id": "actor.evaluator"}, {"id": "binding.evaluator"}, {"id": "profile.v1"},
        {"id": "method.checks"}, {"id": "subject.x", "digest": "sha256:x"},
        {"id": "authority.evaluation"}, {"id": "request.x"},
        {"verification_attempt_id": "vat-1", "request_id": "request.x"},
        {"source": "forge", "log": "log-ref"}, {"state": state}, failure,
    )


class ForgeEnrichmentTests(unittest.TestCase):
    def test_valid_enrichment(self):
        p = StaticForgeEnrichmentProvider(enrichment())
        self.assertIsNotNone(p.enrich(verification_attempt_id="vat-1", provider_output={"verification_attempt_id": "vat-1"}))

    def test_attempt_mismatch_rejected(self):
        p = StaticForgeEnrichmentProvider(enrichment())
        with self.assertRaisesRegex(EnrichmentError, "correlation"):
            p.enrich(verification_attempt_id="vat-2", provider_output={"verification_attempt_id": "vat-1"})

    def test_unavailable_requires_failure(self):
        p = StaticForgeEnrichmentProvider(enrichment("unavailable"))
        with self.assertRaisesRegex(EnrichmentError, "failure"):
            p.enrich(verification_attempt_id="vat-1", provider_output={"verification_attempt_id": "vat-1"})

    def test_invalid_availability_rejected(self):
        p = StaticForgeEnrichmentProvider(enrichment("unknown"))
        with self.assertRaisesRegex(EnrichmentError, "availability"):
            p.enrich(verification_attempt_id="vat-1", provider_output={"verification_attempt_id": "vat-1"})


if __name__ == "__main__":
    unittest.main()
