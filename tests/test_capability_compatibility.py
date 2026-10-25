import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from capabilities.compatibility import (
    CompatibilityEvaluator,
    CompatibilityEvidence,
    CompatibilityInputError,
)


NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)
SCOPE = {"scope_type": "project", "scope_id": "fixture.compatibility"}


def reference(
    semantic_type: str,
    identifier: str,
    version: str = "1.0.0",
    **extra,
):
    return {
        "semantic_type": semantic_type,
        "id": identifier,
        "version": version,
        **extra,
    }


class CapabilityCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = reference(
            "contract",
            "fixture.contract.compile",
            "2.0.0",
            issuer="fixture.source-owner",
        )
        self.target = reference(
            "contract",
            "fixture.contract.compile",
            "1.0.0",
            issuer="fixture.target-owner",
        )
        self.evaluator = CompatibilityEvaluator(
            evaluator_id="fixture.compatibility-evaluator",
            authority_binding=reference(
                "authority_binding", "authority.fixture-compatibility"
            ),
            recognized_evidence_issuers={
                "fixture.independent-evaluator": {
                    "authority.fixture-independent-evaluator"
                }
            },
        )

    def evidence(
        self,
        dimension: str,
        *,
        result: str = "backward_compatible",
        valid_until: datetime | None = None,
        issuer: str = "fixture.independent-evaluator",
        authority_id: str = "authority.fixture-independent-evaluator",
    ) -> CompatibilityEvidence:
        payload = {
            "check": f"fixture-{dimension}-compatibility",
            "result": result,
            "samples": 2,
        }
        candidate = CompatibilityEvidence(
            evidence_id=f"evidence.compatibility.{dimension}",
            version="1.0.0",
            source=self.source,
            target=self.target,
            dimension=dimension,
            result=result,
            change_impact="behavioral",
            method=reference(
                "evaluation_definition", f"eval.compatibility-{dimension}"
            ),
            environment=reference("environment", "fixture.env.compatibility"),
            payload=payload,
            digest="",
            issuer=issuer,
            authority_binding=reference("authority_binding", authority_id),
            observed_at=NOW - timedelta(minutes=1),
            validity_scope=SCOPE,
            valid_until=valid_until,
        )
        return replace(candidate, digest=candidate.expected_digest())

    @staticmethod
    def redigest(evidence: CompatibilityEvidence) -> CompatibilityEvidence:
        return replace(evidence, digest=evidence.expected_digest())

    def complete_evidence(self, result: str = "backward_compatible"):
        return [
            self.evidence(dimension, result=result)
            for dimension in ("structural", "semantic", "behavioral", "operational")
        ]

    def evaluate(self, evidence, direction="backward"):
        return self.evaluator.evaluate(
            source=self.source,
            target=self.target,
            requested_direction=direction,
            required_dimensions=("structural", "semantic", "behavioral", "operational"),
            evidence=evidence,
            validity_scope=SCOPE,
            evaluated_at=NOW,
        )

    def test_backward_compatibility_requires_all_dimensions(self) -> None:
        assessment = self.evaluate(self.complete_evidence())

        self.assertEqual(assessment.outcome, "compatible")
        self.assertEqual(len(assessment.dimension_results), 4)
        self.assertTrue(
            all(item.outcome == "compatible" for item in assessment.dimension_results)
        )
        self.assertFalse(assessment.findings)
        self.assertEqual(assessment.issuer, "fixture.compatibility-evaluator")
        self.assertEqual(
            assessment.authority_binding["id"], "authority.fixture-compatibility"
        )
        self.assertTrue(
            all(
                item.method is not None
                and item.environment is not None
                and item.change_impact == "behavioral"
                for item in assessment.dimension_results
            )
        )

    def test_mutual_evidence_satisfies_each_requested_direction(self) -> None:
        evidence = self.complete_evidence("mutually_compatible")

        for direction in ("backward", "forward", "mutual"):
            self.assertEqual(self.evaluate(evidence, direction).outcome, "compatible")

    def test_different_direction_does_not_imply_incompatibility(self) -> None:
        assessment = self.evaluate(self.complete_evidence("forward_compatible"))

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn(
            "DIRECTION_NOT_ESTABLISHED", {item.code for item in assessment.findings}
        )

    def test_explicit_incompatibility_dominates_compatible_dimensions(self) -> None:
        evidence = self.complete_evidence()
        evidence[1] = self.evidence("semantic", result="incompatible")

        assessment = self.evaluate(evidence)

        self.assertEqual(assessment.outcome, "incompatible")
        semantic = next(
            item
            for item in assessment.dimension_results
            if item.dimension == "semantic"
        )
        self.assertEqual(semantic.outcome, "incompatible")

    def test_missing_evidence_remains_unknown_without_version_inference(self) -> None:
        assessment = self.evaluate([])

        self.assertEqual(assessment.outcome, "unknown")
        self.assertEqual(
            {item.code for item in assessment.findings}, {"EVIDENCE_MISSING"}
        )

    def test_expired_evidence_remains_expired(self) -> None:
        evidence = self.complete_evidence()
        evidence[3] = self.evidence(
            "operational", valid_until=NOW - timedelta(seconds=1)
        )

        assessment = self.evaluate(evidence)

        self.assertEqual(assessment.outcome, "expired")
        self.assertIn("EVIDENCE_EXPIRED", {item.code for item in assessment.findings})

    def test_forged_digest_cannot_establish_compatibility(self) -> None:
        evidence = self.complete_evidence()
        evidence[0] = replace(evidence[0], digest="sha256:forged")

        assessment = self.evaluate(evidence)

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn("DIGEST_MISMATCH", {item.code for item in assessment.findings})

    def test_subject_issuer_cannot_self_certify_compatibility(self) -> None:
        evaluator = CompatibilityEvaluator(
            evaluator_id="fixture.compatibility-evaluator",
            authority_binding=reference(
                "authority_binding", "authority.fixture-compatibility"
            ),
            recognized_evidence_issuers={
                "fixture.source-owner": {"authority.fixture-source"}
            },
        )
        evidence = self.complete_evidence()
        self_certified = replace(
            evidence[0],
            issuer="fixture.source-owner",
            authority_binding=reference(
                "authority_binding", "authority.fixture-source"
            ),
            digest="",
        )
        evidence[0] = self.redigest(self_certified)

        assessment = evaluator.evaluate(
            source=self.source,
            target=self.target,
            requested_direction="backward",
            required_dimensions=("structural", "semantic", "behavioral", "operational"),
            evidence=evidence,
            validity_scope=SCOPE,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn(
            "SELF_CERTIFICATION_PROHIBITED",
            {item.code for item in assessment.findings},
        )

    def test_cross_version_evidence_is_not_reused_silently(self) -> None:
        evidence = self.complete_evidence()
        mismatched = replace(
            evidence[0],
            target=reference(
                "contract",
                "fixture.contract.compile",
                "0.9.0",
                issuer="fixture.target-owner",
            ),
            digest="",
        )
        evidence[0] = self.redigest(mismatched)

        assessment = self.evaluate(evidence)

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn("TARGET_MISMATCH", {item.code for item in assessment.findings})

    def test_contradictory_active_evidence_is_ambiguous(self) -> None:
        evidence = self.complete_evidence()
        conflicting = replace(
            self.evidence("behavioral", result="incompatible"),
            evidence_id="evidence.compatibility.behavioral-conflict",
            digest="",
        )
        evidence.append(self.redigest(conflicting))

        assessment = self.evaluate(evidence)

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn("EVIDENCE_AMBIGUOUS", {item.code for item in assessment.findings})

    def test_future_effective_evidence_is_unknown(self) -> None:
        evidence = self.complete_evidence()
        future = replace(
            evidence[0], effective_from=NOW + timedelta(hours=1), digest=""
        )
        evidence[0] = self.redigest(future)

        assessment = self.evaluate(evidence)

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn(
            "EVIDENCE_NOT_EFFECTIVE", {item.code for item in assessment.findings}
        )

    def test_assessment_contains_no_selection_policy_binding_or_execution(self) -> None:
        payload = asdict(self.evaluate(self.complete_evidence()))

        for prohibited in (
            "selected_candidate",
            "policy_decision",
            "binding_id",
            "authorized",
            "execution",
        ):
            self.assertNotIn(prohibited, payload)

    def test_invalid_request_fails_before_evaluation(self) -> None:
        with self.assertRaisesRegex(CompatibilityInputError, "unique recognized"):
            self.evaluator.evaluate(
                source=self.source,
                target=self.target,
                requested_direction="backward",
                required_dimensions=("semantic", "semantic"),
                evidence=[],
                validity_scope=SCOPE,
                evaluated_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
