import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from capabilities.conformance import (
    CapabilityContractValidator,
    ConformanceEvidence,
    ConformanceEvaluator,
    ConformanceInputError,
)


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "capability-definition" / "robotics-controller.json"
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def reference(semantic_type: str, identifier: str, version: str = "1.0.0", **extra):
    return {
        "semantic_type": semantic_type,
        "id": identifier,
        "version": version,
        **extra,
    }


class CapabilityConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        cls.documents = {
            document["entity_type"]: document for document in example["documents"]
        }
        cls.capability = cls.documents["capability_definition"]
        cls.implementation = cls.documents["implementation_descriptor"]
        cls.validator = CapabilityContractValidator()

    def setUp(self) -> None:
        self.evaluator = ConformanceEvaluator(
            evaluator_id="fixture.conformance-evaluator",
            authority_binding=reference(
                "authority_binding", "authority.fixture-conformance"
            ),
            recognized_evidence_issuers={
                "fixture.independent-evaluator": {
                    "authority.fixture-independent-evaluator"
                },
                "fixture.implementation-author": {"authority.fixture-implementation"},
            },
            validator=self.validator,
        )

    def evidence(
        self,
        dimension: str,
        *,
        outcome: str = "satisfied",
        issuer: str = "fixture.independent-evaluator",
        authority_id: str = "authority.fixture-independent-evaluator",
        valid_until: datetime | None = None,
    ) -> ConformanceEvidence:
        evidence_id = f"evidence.robotics.{dimension}"
        payload = {
            "check": f"fixture-{dimension}-check",
            "result": outcome,
            "sample_count": 2,
        }
        candidate = ConformanceEvidence(
            evidence_id=evidence_id,
            version="1.0.0",
            subject=reference(
                "implementation_descriptor",
                self.implementation["implementation_id"],
                self.implementation["version"],
                digest=self.implementation["digest"],
            ),
            capability=reference(
                "capability_definition",
                self.capability["capability_id"],
                self.capability["version"],
            ),
            contracts=(reference("contract", "execution-result", "1.x"),),
            dimension=dimension,
            outcome=outcome,
            method=reference("evaluation_definition", f"eval.fixture-{dimension}"),
            environment=reference("environment", "fixture.env.robotics"),
            payload=payload,
            digest="",
            issuer=issuer,
            authority_binding=reference("authority_binding", authority_id),
            observed_at=NOW - timedelta(minutes=1),
            valid_until=valid_until,
            validity_scope={
                "scope_type": "test",
                "scope_id": "robotics-controller-example",
            },
            limitations=(),
        )
        return replace(candidate, digest=candidate.expected_digest())

    def complete_evidence(self):
        return [
            self.evidence(dimension)
            for dimension in ("structural", "semantic", "behavioral", "operational")
        ]

    @staticmethod
    def redigest(evidence: ConformanceEvidence) -> ConformanceEvidence:
        return replace(evidence, digest=evidence.expected_digest())

    def test_contract_validator_returns_stable_structural_errors(self) -> None:
        invalid = copy.deepcopy(self.capability)
        invalid["semantic_operations"] = ["Inference"]

        result = self.validator.validate(invalid)

        self.assertFalse(result.valid)
        self.assertTrue(result.errors)
        self.assertIn("not valid under any of the given schemas", result.errors[0])

    def test_complete_independent_evidence_produces_four_valid_claims(self) -> None:
        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=self.complete_evidence(),
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "satisfied")
        self.assertEqual(len(assessment.claims), 4)
        self.assertFalse(assessment.findings)
        for claim in assessment.claims:
            self.assertTrue(self.validator.validate(claim).valid)
            self.assertEqual(claim["issuer"], "fixture.conformance-evaluator")
            self.assertEqual(len(claim["supports"]), 1)
            self.assertEqual(
                claim["validity"]["scope"],
                {"scope_type": "test", "scope_id": "robotics-controller-example"},
            )
            self.assertNotIn("authorized", claim)
            self.assertNotIn("policy_decision", claim)

    def test_failed_evidence_produces_failed_claim_and_assessment(self) -> None:
        evidence = self.complete_evidence()
        evidence[2] = self.evidence("behavioral", outcome="failed")

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "failed")
        behavioral = next(
            claim for claim in assessment.claims if claim["dimension"] == "behavioral"
        )
        self.assertEqual(behavioral["outcome"], "failed")

    def test_expired_evidence_remains_expired_not_satisfied(self) -> None:
        evidence = self.complete_evidence()
        evidence[3] = self.evidence(
            "operational", valid_until=NOW - timedelta(seconds=1)
        )

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "expired")
        operational = next(
            claim for claim in assessment.claims if claim["dimension"] == "operational"
        )
        self.assertEqual(operational["outcome"], "expired")
        self.assertIn("EVIDENCE_EXPIRED", {item.code for item in assessment.findings})

    def test_missing_dimension_remains_unknown_without_fabricated_claim(self) -> None:
        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=self.complete_evidence()[:-1],
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "unknown")
        self.assertEqual(len(assessment.claims), 3)
        self.assertIn("EVIDENCE_MISSING", {item.code for item in assessment.findings})

    def test_digest_mismatch_rejects_evidence_support(self) -> None:
        evidence = self.complete_evidence()
        evidence[0] = replace(evidence[0], digest="sha256:forged")

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn("DIGEST_MISMATCH", {item.code for item in assessment.findings})
        self.assertNotIn(
            "structural", {claim["dimension"] for claim in assessment.claims}
        )

    def test_evidence_semantics_cannot_change_without_invalidating_digest(self) -> None:
        evidence = self.complete_evidence()
        evidence[0] = replace(evidence[0], outcome="failed")

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertIn("DIGEST_MISMATCH", {item.code for item in assessment.findings})
        self.assertEqual(assessment.outcome, "unknown")

    def test_unrecognized_issuer_cannot_support_a_claim(self) -> None:
        evidence = self.complete_evidence()
        evidence[0] = self.evidence(
            "structural",
            issuer="fixture.unrecognized",
            authority_id="authority.fixture-unrecognized",
        )

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertIn(
            "EVIDENCE_ISSUER_UNRECOGNIZED",
            {item.code for item in assessment.findings},
        )
        self.assertEqual(assessment.outcome, "unknown")

    def test_implementation_issuer_cannot_self_certify(self) -> None:
        evidence = self.complete_evidence()
        evidence[1] = self.evidence(
            "semantic",
            issuer="fixture.implementation-author",
            authority_id="authority.fixture-implementation",
        )

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertIn(
            "SELF_CERTIFICATION_PROHIBITED",
            {item.code for item in assessment.findings},
        )
        self.assertEqual(assessment.outcome, "unknown")

    def test_subject_mismatch_does_not_create_conformance(self) -> None:
        evidence = self.complete_evidence()
        evidence[0] = replace(
            evidence[0],
            subject=reference(
                "implementation_descriptor", "fixture.impl.different", digest="sha256:x"
            ),
        )

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertIn("SUBJECT_MISMATCH", {item.code for item in assessment.findings})
        self.assertEqual(assessment.outcome, "unknown")

    def test_duplicate_unsuperseded_evidence_is_ambiguous(self) -> None:
        evidence = self.complete_evidence()
        evidence.append(self.evidence("structural"))

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertIn("EVIDENCE_AMBIGUOUS", {item.code for item in assessment.findings})
        self.assertEqual(assessment.outcome, "unknown")

    def test_invalid_or_undeclared_subjects_fail_closed(self) -> None:
        invalid = copy.deepcopy(self.implementation)
        invalid["declared_capabilities"] = [
            reference("capability_definition", "application.different")
        ]
        with self.assertRaisesRegex(
            ConformanceInputError, "does not declare the assessed capability"
        ):
            self.evaluator.evaluate(
                capability=self.capability,
                implementation=invalid,
                evidence=self.complete_evidence(),
                evaluated_at=NOW,
            )

        malformed = copy.deepcopy(self.implementation)
        del malformed["issuer"]
        with self.assertRaisesRegex(ConformanceInputError, "structurally invalid"):
            self.evaluator.evaluate(
                capability=self.capability,
                implementation=malformed,
                evidence=self.complete_evidence(),
                evaluated_at=NOW,
            )

    def test_naive_evaluation_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConformanceInputError, "timezone-aware"):
            self.evaluator.evaluate(
                capability=self.capability,
                implementation=self.implementation,
                evidence=self.complete_evidence(),
                evaluated_at=datetime(2026, 8, 25, 12, 0),
            )

    def test_unknown_evidence_dimension_is_rejected(self) -> None:
        invalid = replace(self.evidence("structural"), dimension="quality")
        with self.assertRaisesRegex(ConformanceInputError, "not recognized"):
            self.evaluator.evaluate(
                capability=self.capability,
                implementation=self.implementation,
                evidence=[invalid],
                evaluated_at=NOW,
            )

    def test_future_effective_evidence_is_not_yet_conformance(self) -> None:
        evidence = self.complete_evidence()
        future = replace(evidence[0], effective_from=NOW + timedelta(days=1), digest="")
        evidence[0] = self.redigest(future)

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn(
            "EVIDENCE_NOT_EFFECTIVE", {item.code for item in assessment.findings}
        )

    def test_future_observation_beyond_clock_skew_is_rejected(self) -> None:
        evidence = self.complete_evidence()
        future = replace(evidence[0], observed_at=NOW + timedelta(minutes=2), digest="")
        evidence[0] = self.redigest(future)

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn(
            "EVIDENCE_FROM_FUTURE", {item.code for item in assessment.findings}
        )

    def test_declared_clock_skew_is_bounded_and_explicit(self) -> None:
        evaluator = ConformanceEvaluator(
            evaluator_id="fixture.conformance-evaluator",
            authority_binding=reference(
                "authority_binding", "authority.fixture-conformance"
            ),
            recognized_evidence_issuers={
                "fixture.independent-evaluator": {
                    "authority.fixture-independent-evaluator"
                }
            },
            allowed_clock_skew=timedelta(seconds=45),
            validator=self.validator,
        )
        evidence = self.complete_evidence()
        skewed = replace(
            evidence[0], observed_at=NOW + timedelta(seconds=30), digest=""
        )
        evidence[0] = self.redigest(skewed)

        assessment = evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "satisfied")

    def test_overlapping_contradictory_evidence_fails_closed(self) -> None:
        evidence = self.complete_evidence()
        contradictory = replace(
            self.evidence("semantic", outcome="failed"),
            evidence_id="evidence.robotics.semantic-conflict",
            digest="",
        )
        evidence.append(self.redigest(contradictory))

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn("EVIDENCE_AMBIGUOUS", {item.code for item in assessment.findings})
        self.assertNotIn(
            "semantic", {claim["dimension"] for claim in assessment.claims}
        )

    def test_revoked_evidence_can_be_explicitly_reissued(self) -> None:
        evidence = self.complete_evidence()
        old = replace(evidence[0], revoked_at=NOW - timedelta(seconds=10), digest="")
        old = self.redigest(old)
        replacement = replace(
            self.evidence("structural"),
            evidence_id="evidence.robotics.structural-reissued",
            supersedes=old.evidence_id,
            digest="",
        )
        replacement = self.redigest(replacement)
        evidence[0:1] = [old, replacement]

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "satisfied")
        self.assertIn("EVIDENCE_REVOKED", {item.code for item in assessment.findings})
        claim = next(
            item for item in assessment.claims if item["dimension"] == "structural"
        )
        self.assertIsNotNone(claim["supersession"])

    def test_different_issuers_do_not_resolve_competing_active_evidence(self) -> None:
        evaluator = ConformanceEvaluator(
            evaluator_id="fixture.conformance-evaluator",
            authority_binding=reference(
                "authority_binding", "authority.fixture-conformance"
            ),
            recognized_evidence_issuers={
                "fixture.independent-evaluator": {
                    "authority.fixture-independent-evaluator"
                },
                "fixture.second-evaluator": {"authority.fixture-second-evaluator"},
            },
            validator=self.validator,
        )
        evidence = self.complete_evidence()
        competing = replace(
            self.evidence("behavioral", outcome="failed"),
            evidence_id="evidence.robotics.behavioral-second",
            issuer="fixture.second-evaluator",
            authority_binding=reference(
                "authority_binding", "authority.fixture-second-evaluator"
            ),
            digest="",
        )
        evidence.append(self.redigest(competing))

        assessment = evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn("EVIDENCE_AMBIGUOUS", {item.code for item in assessment.findings})

    def test_cross_version_evidence_requires_explicit_compatibility(self) -> None:
        evidence = self.complete_evidence()
        wrong_version = replace(
            evidence[1],
            capability=reference(
                "capability_definition", self.capability["capability_id"], "0.9.0"
            ),
            digest="",
        )
        evidence[1] = self.redigest(wrong_version)

        assessment = self.evaluator.evaluate(
            capability=self.capability,
            implementation=self.implementation,
            evidence=evidence,
            evaluated_at=NOW,
        )

        self.assertEqual(assessment.outcome, "unknown")
        self.assertIn(
            "CAPABILITY_MISMATCH", {item.code for item in assessment.findings}
        )


if __name__ == "__main__":
    unittest.main()
