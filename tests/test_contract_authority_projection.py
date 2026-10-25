import hashlib
import json
import unittest
from pathlib import Path

from capabilities.contract_authority import (
    ContractAuthorityValidator,
    PromotionDecision,
    SourceArtifact,
    sha256_digest,
)


ROOT = Path(__file__).parents[1]


class ContractAuthorityProjectionQualificationTests(unittest.TestCase):
    revision = "commit-fixture-001"

    def setUp(self) -> None:
        self.validator = ContractAuthorityValidator()
        schema_content = b"schema-source"
        promotion_content = b"promotion-source"
        binding_content = b"binding-source"
        schema_digest = sha256_digest(schema_content)
        promotion_digest = sha256_digest(promotion_content)
        binding_digest = sha256_digest(binding_content)
        self.schema_key = ("contract_schema", "example-contract.v1", "1.0.0")
        self.promotion_key = ("promotion_record", "example-contract-promotion", "1.0.0")
        self.sources = {
            self.schema_key: SourceArtifact("contract_schema", "example-contract.v1", "1.0.0", schema_digest, True, self.revision, "example-contract.v1", schema_content),
            self.promotion_key: SourceArtifact("promotion_record", "example-contract-promotion", "1.0.0", promotion_digest, True, self.revision, content=promotion_content),
            ("authority_binding", "core-contract-authority", "1.0.0"): SourceArtifact("authority_binding", "core-contract-authority", "1.0.0", binding_digest, True, self.revision, content=binding_content),
        }
        self.projection = self._projection(schema_digest, promotion_digest)

    def _projection(self, schema_digest: str, promotion_digest: str) -> dict:
        ref = lambda semantic_type, identifier, version, digest: {"semantic_type": semantic_type, "id": identifier, "version": version, "digest": digest}
        return {
            "schema": "contract-authority-projection.v1",
            "record_type": "contract_authority_projection",
            "projection_id": "example-contract-authority-projection",
            "contract": {"family": "example-contract", "version": "1.0.0", "schema_id": "example-contract.v1", "schema_digest": schema_digest, "issuer": "core"},
            "authority": {"disposition": "promoted", "promotion_decision_ref": ref("promotion_record", "example-contract-promotion", "1.0.0", promotion_digest), "authority_binding_ref": ref("authority_binding", "core-contract-authority", "1.0.0", sha256_digest(b"binding-source")), "validity_scope": {"scope_type": "platform", "scope_id": "core"}},
            "status_dimensions": {
                "implementation": {"status": "absent", "evidence_refs": []},
                "conformance": {"status": "not_assessed", "evidence_refs": []},
                "qualification": {"status": "not_assessed", "evidence_refs": []},
                "lifecycle": {"status": "active", "supersession_ref": None, "deprecation_ref": None},
                "baseline": {"freeze_status": "not_in_baseline", "evidence_refs": []},
            },
            "evidence": [],
            "reconciliation": {"outcome": "VALID", "reason_codes": [], "blocking": False},
            "admissibility": {"contract_authoritative": True, "contract_use": "semantic_reference", "blocked_reasons": []},
            "provenance": {"source_revision": self.revision, "source_digests": [schema_digest, promotion_digest, sha256_digest(b"binding-source")], "reproducibility": {"status": "reproducible"}, "projection_digest": "sha256:" + "0" * 64},
        }

    def _decisions(self) -> tuple[PromotionDecision, ...]:
        return (PromotionDecision("example-contract", "1.0.0", self.promotion_key, "promoted"),)

    def _with_projection_digest(self, projection: dict) -> dict:
        material = json.loads(json.dumps(projection))
        material["provenance"].pop("projection_digest", None)
        projection["provenance"]["projection_digest"] = sha256_digest(json.dumps(material, sort_keys=True, separators=(",", ":")).encode())
        return projection

    def test_clean_promoted_contract_is_valid_without_implementation(self) -> None:
        result = self.validator.validate(self._with_projection_digest(self.projection), sources=self.sources, promotion_decisions=self._decisions(), source_revision=self.revision)
        self.assertTrue(result.valid)
        self.assertEqual(result.outcome, "VALID", [(finding.reason_code, finding.detail) for finding in result.findings])
        self.assertEqual(result.reproducibility, "reproducible")
        self.assertTrue(result.contract_authoritative)
        self.assertTrue(result.contract_admissible)

    def test_untracked_promotion_is_unresolved_and_not_authoritative(self) -> None:
        sources = dict(self.sources)
        sources[self.promotion_key] = SourceArtifact(*self.promotion_key, self.sources[self.promotion_key].digest, False, self.revision)
        projection = json.loads(json.dumps(self.projection))
        projection["reconciliation"] = {"outcome": "UNRESOLVED", "reason_codes": ["SOURCE_NOT_REPRODUCIBLE", "UNTRACKED_AUTHORITY_SOURCE"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["SOURCE_NOT_REPRODUCIBLE", "UNTRACKED_AUTHORITY_SOURCE"]}
        projection["provenance"]["reproducibility"] = {"status": "non_reproducible", "reason_codes": ["UNTRACKED_AUTHORITY_SOURCE"]}
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(projection, sources=sources, promotion_decisions=self._decisions(), source_revision=self.revision)
        self.assertEqual(result.outcome, "UNRESOLVED")
        self.assertEqual(result.reproducibility, "non_reproducible")
        self.assertFalse(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)

    def test_source_content_digest_mismatch_is_invalid(self) -> None:
        sources = dict(self.sources)
        source = sources[self.schema_key]
        sources[self.schema_key] = SourceArtifact(
            source.semantic_type, source.identifier, source.version, source.digest,
            source.tracked, source.revision, source.declared_schema_id, b"mutated-source"
        )
        projection = self._with_projection_digest(json.loads(json.dumps(self.projection)))
        projection["reconciliation"] = {"outcome": "INVALID", "reason_codes": ["DIGEST_MISMATCH"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["DIGEST_MISMATCH"]}
        result = self.validator.validate(projection, sources=sources, promotion_decisions=self._decisions(), source_revision=self.revision)
        self.assertEqual(result.outcome, "INVALID")
        self.assertIn("DIGEST_MISMATCH", {finding.reason_code for finding in result.findings})

    def test_missing_positive_status_evidence_is_unresolved(self) -> None:
        projection = json.loads(json.dumps(self.projection))
        projection["status_dimensions"]["qualification"] = {"status": "qualified", "evidence_refs": []}
        projection["reconciliation"] = {"outcome": "UNRESOLVED", "reason_codes": ["EVIDENCE_MISSING"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["EVIDENCE_MISSING"]}
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(projection, sources=self.sources, promotion_decisions=self._decisions(), source_revision=self.revision)
        self.assertEqual(result.outcome, "UNRESOLVED")
        self.assertIn("EVIDENCE_MISSING", {finding.reason_code for finding in result.findings})

    def test_projection_digest_mismatch_is_invalid(self) -> None:
        projection = self._with_projection_digest(json.loads(json.dumps(self.projection)))
        projection["provenance"]["projection_digest"] = "sha256:" + "9" * 64
        projection["reconciliation"] = {"outcome": "INVALID", "reason_codes": ["DIGEST_MISMATCH"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["DIGEST_MISMATCH"]}
        result = self.validator.validate(projection, sources=self.sources, promotion_decisions=self._decisions(), source_revision=self.revision)
        self.assertEqual(result.outcome, "INVALID")
        self.assertIn("DIGEST_MISMATCH", {finding.reason_code for finding in result.findings})

    def test_digest_mismatch_is_invalid_and_blocked(self) -> None:
        projection = self._with_projection_digest(json.loads(json.dumps(self.projection)))
        projection["contract"]["schema_digest"] = "sha256:" + "9" * 64
        projection["reconciliation"] = {"outcome": "INVALID", "reason_codes": ["DIGEST_MISMATCH"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["DIGEST_MISMATCH"]}
        result = self.validator.validate(projection, sources=self.sources, promotion_decisions=self._decisions(), source_revision=self.revision)
        self.assertEqual(result.outcome, "INVALID")
        self.assertFalse(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)
        self.assertIn("DIGEST_MISMATCH", {finding.reason_code for finding in result.findings})

    def test_multiple_promotion_decisions_are_contradictory(self) -> None:
        projection = self._with_projection_digest(json.loads(json.dumps(self.projection)))
        projection["reconciliation"] = {"outcome": "CONTRADICTORY", "reason_codes": ["MULTIPLE_AUTHORITY_DECISIONS"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["MULTIPLE_AUTHORITY_DECISIONS"]}
        decisions = self._decisions() + (PromotionDecision("example-contract", "1.0.0", ("promotion_record", "other-promotion", "1.0.0"), "candidate"),)
        result = self.validator.validate(projection, sources=self.sources, promotion_decisions=decisions, source_revision=self.revision)
        self.assertEqual(result.outcome, "CONTRADICTORY")
        self.assertFalse(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)

    def test_superseded_contract_retains_no_current_admissibility(self) -> None:
        projection = json.loads(json.dumps(self.projection))
        replacement_content = b"replacement-contract"
        replacement_digest = sha256_digest(replacement_content)
        sources = dict(self.sources)
        sources[("supersession", "example-contract.v2", "2.0.0")] = SourceArtifact(
            "supersession", "example-contract.v2", "2.0.0", replacement_digest, True, self.revision, content=replacement_content
        )
        projection["status_dimensions"]["lifecycle"] = {
            "status": "superseded",
            "supersession_ref": {
                "semantic_type": "supersession",
                "id": "example-contract.v2",
                "version": "2.0.0",
                "digest": replacement_digest,
            },
            "deprecation_ref": None,
        }
        projection["provenance"]["source_digests"].append(replacement_digest)
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(projection, sources=sources, promotion_decisions=self._decisions(), source_revision=self.revision)
        self.assertEqual(result.outcome, "VALID")
        self.assertTrue(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)

    def test_structural_failure_is_invalid(self) -> None:
        projection = dict(self.projection)
        del projection["contract"]
        result = self.validator.validate(projection)
        self.assertFalse(result.structural_valid)
        self.assertEqual(result.outcome, "INVALID")

    def test_projection_digest_helper_is_stable(self) -> None:
        payload = b"authority-source"
        self.assertEqual(sha256_digest(payload), "sha256:" + hashlib.sha256(payload).hexdigest())

    def test_synthetic_delegation_candidate_status_blocks_promotion(self) -> None:
        """Validator conformance must not depend on mutable worktree evidence."""
        schema_id = "delegation.v1"
        source_content = b'{"$id":"delegation.v1","x-status":"candidate-only"}'
        digest = sha256_digest(source_content)
        promotion_content = b"synthetic delegation promotion record"
        review_content = b"synthetic delegation final review"
        qualification_content = b"synthetic delegation implementation qualification gate"
        promotion_key = ("promotion_record", "delegation-promotion", "1.0.0")
        review_key = ("review_evidence", "delegation-final-review", "1.0.0")
        qualification_key = ("qualification_evidence", "delegation-implementation-gate", "1.0.0")
        promotion_digest = sha256_digest(promotion_content)
        review_digest = sha256_digest(review_content)
        qualification_digest = sha256_digest(qualification_content)
        projection = self._projection(digest, promotion_digest)
        projection["contract"].update({"family": "delegation", "schema_id": schema_id})
        projection["authority"]["promotion_decision_ref"] = {"semantic_type": promotion_key[0], "id": promotion_key[1], "version": promotion_key[2], "digest": promotion_digest}
        projection["evidence"] = [
            {"evidence_type": "review", "reference": {"semantic_type": review_key[0], "id": review_key[1], "version": review_key[2], "digest": review_digest}, "supports_dimension": "authority"},
            {"evidence_type": "qualification", "reference": {"semantic_type": qualification_key[0], "id": qualification_key[1], "version": qualification_key[2], "digest": qualification_digest}, "supports_dimension": "qualification"},
        ]
        projection["provenance"]["source_digests"].extend([review_digest, qualification_digest])
        sources = dict(self.sources)
        sources.pop(self.schema_key)
        sources.pop(self.promotion_key)
        sources[("contract_schema", schema_id, "1.0.0")] = SourceArtifact(
            "contract_schema", schema_id, "1.0.0", digest, False, self.revision,
            declared_schema_id=schema_id,
            content=source_content,
            declared_status="candidate-only",
            path_identity=schema_id,
        )
        sources[promotion_key] = SourceArtifact(*promotion_key, promotion_digest, False, self.revision, content=promotion_content, declared_status="promoted")
        sources[review_key] = SourceArtifact(*review_key, review_digest, False, self.revision, content=review_content)
        sources[qualification_key] = SourceArtifact(*qualification_key, qualification_digest, False, self.revision, content=qualification_content)
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(
            projection,
            sources=sources,
            promotion_decisions=(PromotionDecision("delegation", "1.0.0", promotion_key, "promoted"),),
            source_revision=self.revision,
        )
        self.assertFalse(result.contract_authoritative)
        self.assertIn("CANDIDATE_PROMOTION_CONFLICT", {finding.reason_code for finding in result.findings})
        self.assertIn("SOURCE_NOT_REPRODUCIBLE", {finding.reason_code for finding in result.findings})

    def test_real_finding_disposition_filename_identity_conflict_is_detected(self) -> None:
        path = ROOT / "contracts" / "finding-disposition.v1.candidate.schema.json"
        source_content = path.read_bytes()
        source_document = json.loads(source_content)
        schema_id = source_document["$id"]
        digest = sha256_digest(source_content)
        projection = self._projection(digest, self.sources[self.promotion_key].digest)
        projection["contract"].update({"family": "finding-disposition", "schema_id": schema_id})
        sources = dict(self.sources)
        sources.pop(self.schema_key)
        sources[("contract_schema", schema_id, "1.0.0")] = SourceArtifact(
            "contract_schema", schema_id, "1.0.0", digest, False, self.revision,
            schema_id, source_content, source_document["x-status"], "finding-disposition.v1.candidate"
        )
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(
            projection,
            sources=sources,
            promotion_decisions=(PromotionDecision("finding-disposition", "1.0.0", self.promotion_key, "promoted"),),
            source_revision=self.revision,
        )
        self.assertFalse(result.contract_authoritative)
        self.assertIn("PATH_ID_MISMATCH", {finding.reason_code for finding in result.findings})

    def _exception_case(self) -> tuple[dict, dict, tuple[str, str, str], tuple[str, str, str]]:
        revision = "git-ref:refs/tags/test/example-source-state-v1"
        schema_content = self.sources[self.schema_key].content
        assert schema_content is not None
        schema_digest = sha256_digest(schema_content)
        schema_source = SourceArtifact(
            "contract_schema", "example-contract.v1", "1.0.0", schema_digest,
            True, revision, "example-contract.v1", schema_content,
            path_identity="example-contract.v1.legacy", artifact_path="contracts/example-contract.v1.schema.json",
        )
        decision_key = ("owner_decision", "example-contract-id-exception", "1.0.0")
        decision_content = b"owner decision: historical path identity exception"
        decision_source = SourceArtifact(
            *decision_key, sha256_digest(decision_content), True, revision,
            content=decision_content,
        )
        exception_key = ("historical_path_identity_exception", "example-contract-id-exception", "1.0.0")
        exception = {
            "schema": "historical-path-identity-exception.v1",
            "record_type": "historical_path_identity_exception",
            "exception_id": "example-contract-id-exception",
            "contract_family": "example-contract",
            "contract_version": "1.0.0",
            "schema_id": "example-contract.v1",
            "artifact_path": "contracts/example-contract.v1.schema.json",
            "source_digest": schema_digest,
            "source_revision": revision,
            "owner_decision_ref": {
                "semantic_type": decision_key[0], "id": decision_key[1],
                "version": decision_key[2], "digest": decision_source.digest,
            },
            "validity_scope": {"scope_type": "historical_compatibility", "scope_id": "core"},
            "exception_status": "active",
            "constraints": {
                "non_authoritative": True,
                "non_admissibility_granting": True,
                "non_transferable": True,
            },
        }
        exception_content = json.dumps(exception, sort_keys=True, separators=(",", ":")).encode()
        exception_source = SourceArtifact(
            *exception_key, sha256_digest(exception_content), True, revision,
            content=exception_content,
        )
        sources = {
            key: SourceArtifact(
                source.semantic_type, source.identifier, source.version, source.digest,
                source.tracked, revision, source.declared_schema_id, source.content,
                source.declared_status, source.path_identity, source.artifact_path,
            )
            for key, source in self.sources.items()
        }
        sources[self.schema_key] = schema_source
        sources[decision_key] = decision_source
        sources[exception_key] = exception_source
        projection = self._with_projection_digest(json.loads(json.dumps(self.projection)))
        projection["provenance"]["source_revision"] = revision
        projection["authority"]["historical_identity_exception_ref"] = {
            "semantic_type": exception_key[0], "id": exception_key[1],
            "version": exception_key[2], "digest": exception_source.digest,
        }
        projection["provenance"]["source_digests"] = [source.digest for source in sources.values()]
        projection["reconciliation"] = {"outcome": "VALID", "reason_codes": ["HISTORICAL_IDENTITY_EXCEPTION_APPLIED"], "blocking": False}
        projection["admissibility"] = {"contract_authoritative": True, "contract_use": "semantic_reference", "blocked_reasons": []}
        projection = self._with_projection_digest(projection)
        projection = self._with_projection_digest(projection)
        return projection, sources, exception_key, decision_key

    def test_valid_historical_exception_explains_identity_without_changing_authority(self) -> None:
        projection, sources, _, _ = self._exception_case()
        result = self.validator.validate(projection, sources=sources, promotion_decisions=self._decisions(), source_revision=projection["provenance"]["source_revision"])
        self.assertEqual(result.outcome, "VALID")
        self.assertIn("HISTORICAL_IDENTITY_EXCEPTION_APPLIED", {finding.reason_code for finding in result.findings})
        self.assertTrue(result.contract_authoritative)
        self.assertTrue(result.contract_admissible)

    def test_untracked_historical_exception_is_unresolved(self) -> None:
        projection, sources, exception_key, _ = self._exception_case()
        source = sources[exception_key]
        sources[exception_key] = SourceArtifact(
            source.semantic_type, source.identifier, source.version, source.digest,
            False, source.revision, content=source.content,
        )
        projection["reconciliation"] = {"outcome": "UNRESOLVED", "reason_codes": ["HISTORICAL_EXCEPTION_UNTRACKED", "PATH_ID_MISMATCH", "SOURCE_NOT_REPRODUCIBLE"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["HISTORICAL_EXCEPTION_UNTRACKED", "PATH_ID_MISMATCH", "SOURCE_NOT_REPRODUCIBLE"]}
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(projection, sources=sources, promotion_decisions=self._decisions(), source_revision=projection["provenance"]["source_revision"])
        self.assertEqual(result.outcome, "UNRESOLVED")
        self.assertFalse(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)

    def test_exception_digest_mismatch_is_invalid(self) -> None:
        projection, sources, exception_key, _ = self._exception_case()
        source = sources[exception_key]
        sources[exception_key] = SourceArtifact(
            source.semantic_type, source.identifier, source.version, source.digest,
            source.tracked, source.revision, content=b"mutated exception",
        )
        projection["reconciliation"] = {"outcome": "INVALID", "reason_codes": ["HISTORICAL_EXCEPTION_DIGEST_INVALID"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["HISTORICAL_EXCEPTION_DIGEST_INVALID"]}
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(projection, sources=sources, promotion_decisions=self._decisions(), source_revision=projection["provenance"]["source_revision"])
        self.assertEqual(result.outcome, "INVALID")
        self.assertFalse(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)

    def test_exception_constraints_cannot_escalate_authority_or_admissibility(self) -> None:
        projection, sources, exception_key, _ = self._exception_case()
        exception = json.loads(sources[exception_key].content)
        exception["constraints"]["non_authoritative"] = False
        content = json.dumps(exception, sort_keys=True, separators=(",", ":")).encode()
        source = sources[exception_key]
        sources[exception_key] = SourceArtifact(
            source.semantic_type, source.identifier, source.version, sha256_digest(content),
            source.tracked, source.revision, content=content,
        )
        ref = projection["authority"]["historical_identity_exception_ref"]
        ref["digest"] = sources[exception_key].digest
        projection["reconciliation"] = {"outcome": "INVALID", "reason_codes": ["HISTORICAL_EXCEPTION_INVALID"], "blocking": True}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": ["HISTORICAL_EXCEPTION_INVALID"]}
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(projection, sources=sources, promotion_decisions=self._decisions(), source_revision=projection["provenance"]["source_revision"])
        self.assertEqual(result.outcome, "INVALID")
        self.assertFalse(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)

    def test_real_finding_disposition_historical_exception_preserves_non_authority(self) -> None:
        revision = "git-ref:refs/tags/test/finding-disposition-source-state-v1"
        path = ROOT / "contracts" / "finding-disposition.v1.candidate.schema.json"
        schema_content = path.read_bytes()
        schema_document = json.loads(schema_content)
        schema_id = schema_document["$id"]
        schema_digest = sha256_digest(schema_content)
        schema_key = ("contract_schema", schema_id, "1.0.0")
        decision_key = ("owner_decision", "finding-disposition-id-exception", "1.0.0")
        decision_content = b"owner decision: retain historical candidate filename"
        decision_source = SourceArtifact(
            *decision_key, sha256_digest(decision_content), True, revision,
            content=decision_content,
        )
        exception_key = ("historical_path_identity_exception", "finding-disposition-id-exception", "1.0.0")
        exception = {
            "schema": "historical-path-identity-exception.v1",
            "record_type": "historical_path_identity_exception",
            "exception_id": "finding-disposition-id-exception",
            "contract_family": "finding-disposition",
            "contract_version": "1.0.0",
            "schema_id": schema_id,
            "artifact_path": "contracts/finding-disposition.v1.candidate.schema.json",
            "source_digest": schema_digest,
            "source_revision": revision,
            "owner_decision_ref": {
                "semantic_type": decision_key[0], "id": decision_key[1],
                "version": decision_key[2], "digest": decision_source.digest,
            },
            "validity_scope": {"scope_type": "historical_compatibility", "scope_id": "core"},
            "exception_status": "active",
            "constraints": {
                "non_authoritative": True,
                "non_admissibility_granting": True,
                "non_transferable": True,
            },
        }
        exception_content = json.dumps(exception, sort_keys=True, separators=(",", ":")).encode()
        exception_source = SourceArtifact(
            *exception_key, sha256_digest(exception_content), True, revision,
            content=exception_content,
        )
        sources = {
            schema_key: SourceArtifact(
                "contract_schema", schema_id, "1.0.0", schema_digest, True,
                revision, schema_id, schema_content,
                schema_document["x-status"], "finding-disposition.v1.candidate",
                "contracts/finding-disposition.v1.candidate.schema.json",
            ),
            decision_key: decision_source,
            exception_key: exception_source,
        }
        projection = self._projection(schema_digest, self.sources[self.promotion_key].digest)
        projection["contract"].update({"family": "finding-disposition", "schema_id": schema_id})
        projection["authority"] = {
            "disposition": "candidate",
            "promotion_decision_ref": None,
            "authority_binding_ref": None,
            "historical_identity_exception_ref": {
                "semantic_type": exception_key[0], "id": exception_key[1],
                "version": exception_key[2], "digest": exception_source.digest,
            },
            "validity_scope": None,
        }
        projection["provenance"]["source_digests"] = [source.digest for source in sources.values()]
        projection["provenance"]["source_revision"] = revision
        projection["provenance"]["reproducibility"] = {"status": "reproducible"}
        projection["reconciliation"] = {"outcome": "VALID", "reason_codes": ["HISTORICAL_IDENTITY_EXCEPTION_APPLIED"], "blocking": False}
        projection["admissibility"] = {"contract_authoritative": False, "contract_use": "semantic_reference", "blocked_reasons": []}
        projection = self._with_projection_digest(projection)
        result = self.validator.validate(projection, sources=sources, source_revision=revision)
        self.assertEqual(result.outcome, "VALID")
        self.assertIn("HISTORICAL_IDENTITY_EXCEPTION_APPLIED", {finding.reason_code for finding in result.findings})
        self.assertFalse(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)

    def test_committed_finding_disposition_exception_projection_fixture(self) -> None:
        revision = "git-ref:refs/tags/core-authority/finding-disposition-source-state-v1"
        schema_path = ROOT / "contracts" / "finding-disposition.v1.candidate.schema.json"
        exception_path = ROOT / "contracts" / "finding-disposition.v1.historical-path-identity-exception.json"
        decision_path = ROOT / "docs" / "assurance" / "CONTRACT-AUTHORITY-OWNER-DECISION-RECORD-v1.md"
        projection_path = ROOT / "fixtures" / "conformance" / "finding-disposition-authority-projection-v1.json"
        schema_content = schema_path.read_bytes()
        exception_content = exception_path.read_bytes()
        decision_content = decision_path.read_bytes()
        projection = json.loads(projection_path.read_bytes())
        schema_document = json.loads(schema_content)
        exception_document = json.loads(exception_content)
        schema_id = schema_document["$id"]
        schema_digest = sha256_digest(schema_content)
        exception_digest = sha256_digest(exception_content)
        decision_digest = sha256_digest(decision_content)
        self.assertEqual(schema_digest, projection["contract"]["schema_digest"])
        self.assertEqual(exception_digest, projection["authority"]["historical_identity_exception_ref"]["digest"])
        self.assertEqual(exception_document["source_revision"], revision)
        sources = {
            ("contract_schema", schema_id, "1.0.0"): SourceArtifact(
                "contract_schema", schema_id, "1.0.0", schema_digest, True, revision,
                schema_id, schema_content, schema_document["x-status"],
                "finding-disposition.v1.candidate", "contracts/finding-disposition.v1.candidate.schema.json",
            ),
            ("owner_decision", "contract-authority-owner-decision", "1.0.0"): SourceArtifact(
                "owner_decision", "contract-authority-owner-decision", "1.0.0", decision_digest,
                True, revision, content=decision_content,
            ),
            ("historical_path_identity_exception", "finding-disposition-id-exception", "1.0.0"): SourceArtifact(
                "historical_path_identity_exception", "finding-disposition-id-exception", "1.0.0", exception_digest,
                True, revision, content=exception_content,
            ),
        }
        result = self.validator.validate(projection, sources=sources, source_revision=revision)
        self.assertEqual(result.outcome, "VALID")
        self.assertEqual(result.reproducibility, "reproducible")
        self.assertIn("HISTORICAL_IDENTITY_EXCEPTION_APPLIED", {finding.reason_code for finding in result.findings})
        self.assertFalse(result.contract_authoritative)
        self.assertFalse(result.contract_admissible)


if __name__ == "__main__":
    unittest.main()
