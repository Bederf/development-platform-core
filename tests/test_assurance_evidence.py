import hashlib

from capabilities.assurance_evidence import AssuranceEvidenceLifecycleValidator
from capabilities.contract_authority import SourceArtifact


def digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def ref(semantic_type: str, identifier: str, version: str, content: bytes) -> dict:
    return {"semantic_type": semantic_type, "id": identifier, "version": version, "digest": digest(content)}


def source(reference: dict, content: bytes, *, tracked: bool = True, revision: str = "git:fixture-001") -> SourceArtifact:
    return SourceArtifact(
        reference["semantic_type"],
        reference["id"],
        reference["version"],
        reference["digest"],
        tracked,
        revision,
        content=content,
    )


def base_record(disposition: str = "candidate") -> tuple[dict, dict[tuple[str, str, str], SourceArtifact]]:
    evidence_content = b"qualification evidence"
    subject_content = b"subject snapshot"
    evidence = ref("qualification_evidence", "evidence-001", "1.0.0", evidence_content)
    subject = ref("implementation", "subject-001", "1.0.0", subject_content)
    sources = {
        (evidence["semantic_type"], evidence["id"], evidence["version"]): source(evidence, evidence_content),
        (subject["semantic_type"], subject["id"], subject["version"]): source(subject, subject_content),
    }
    record = {
        "schema": "assurance-evidence-promotion.v1",
        "record_type": "assurance_evidence_promotion",
        "promotion_id": "promotion-001",
        "evidence_ref": evidence,
        "subject_ref": subject,
        "validity_scope": {"scope_type": "platform", "scope_id": "core"},
        "supports": ["qualification"],
        "review_refs": [],
        "acceptance_refs": [],
        "authority_decision_ref": None,
        "source_revision": "git:fixture-001",
        "disposition": disposition,
        "supersedes_ref": None,
        "reason_codes": [],
        "provenance": {"source_digests": [evidence["digest"], subject["digest"]], "reproducibility": "reproducible"},
    }
    return record, sources


def add_promoted_sources(record: dict, sources: dict) -> dict:
    authority_content = b"owner promotion decision"
    review_content = b"independent review"
    acceptance_content = b"owner acceptance"
    authority = ref("promotion_record", "promotion-record-001", "1.0.0", authority_content)
    review = ref("review_evidence", "review-001", "1.0.0", review_content)
    acceptance = ref("acceptance_evidence", "acceptance-001", "1.0.0", acceptance_content)
    record["disposition"] = "promoted"
    record["authority_decision_ref"] = authority
    record["review_refs"] = [review]
    record["acceptance_refs"] = [acceptance]
    record["provenance"]["source_digests"].extend([authority["digest"], review["digest"], acceptance["digest"]])
    for reference, content in ((authority, authority_content), (review, review_content), (acceptance, acceptance_content)):
        sources[(reference["semantic_type"], reference["id"], reference["version"])] = source(reference, content)
    return {
        "disposition": "promoted",
        "evidence_ref": record["evidence_ref"],
        "validity_scope": record["validity_scope"],
        "supports": record["supports"],
    }


def test_candidate_is_non_authoritative_and_valid() -> None:
    record, sources = base_record()
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001")
    assert result.structural_valid
    assert result.disposition == "candidate"
    assert not result.authoritative_eligible
    assert result.reproducibility == "reproducible"
    assert result.findings == ()


def test_promoted_record_requires_exact_review_acceptance_and_authority_binding() -> None:
    record, sources = base_record()
    decision = add_promoted_sources(record, sources)
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001", authority_decision=decision)
    assert result.authoritative_eligible
    assert result.reproducibility == "reproducible"
    assert result.findings == ()


def test_promoted_record_rejects_authority_scope_or_identity_mismatch() -> None:
    record, sources = base_record()
    decision = add_promoted_sources(record, sources)
    decision["validity_scope"] = {"scope_type": "consumer", "scope_id": "other"}
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001", authority_decision=decision)
    assert not result.authoritative_eligible
    assert "AUTHORITY_SCOPE_MISMATCH" in {finding.code for finding in result.findings}


def test_promoted_record_requires_external_authority_facts() -> None:
    record, sources = base_record()
    add_promoted_sources(record, sources)
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001")
    assert not result.authoritative_eligible
    assert "MISSING_AUTHORITY_DECISION" in {finding.code for finding in result.findings}


def test_untracked_promoted_source_is_blocked() -> None:
    record, sources = base_record()
    decision = add_promoted_sources(record, sources)
    authority_key = ("promotion_record", "promotion-record-001", "1.0.0")
    authority = sources[authority_key]
    sources[authority_key] = SourceArtifact(
        authority.semantic_type, authority.identifier, authority.version,
        authority.digest, False, authority.revision, content=authority.content,
    )
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001", authority_decision=decision)
    assert not result.authoritative_eligible
    assert "SOURCE_NOT_REPRODUCIBLE" in {finding.code for finding in result.findings}


def test_digest_mismatch_is_invalid_for_promoted_evidence() -> None:
    record, sources = base_record()
    decision = add_promoted_sources(record, sources)
    evidence_key = ("qualification_evidence", "evidence-001", "1.0.0")
    evidence = sources[evidence_key]
    sources[evidence_key] = SourceArtifact(
        evidence.semantic_type, evidence.identifier, evidence.version,
        evidence.digest, evidence.tracked, evidence.revision, content=b"tampered",
    )
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001", authority_decision=decision)
    assert not result.authoritative_eligible
    assert "DIGEST_MISMATCH" in {finding.code for finding in result.findings}


def test_revision_mismatch_is_blocked() -> None:
    record, sources = base_record()
    add_promoted_sources(record, sources)
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:other-002")
    assert not result.authoritative_eligible
    assert "SOURCE_REVISION_MISMATCH" in {finding.code for finding in result.findings}


def test_candidate_cannot_carry_authority_decision() -> None:
    record, sources = base_record()
    authority_content = b"owner promotion decision"
    authority = ref("promotion_record", "promotion-record-001", "1.0.0", authority_content)
    record["authority_decision_ref"] = authority
    record["provenance"]["source_digests"].append(authority["digest"])
    sources[(authority["semantic_type"], authority["id"], authority["version"])] = source(authority, authority_content)
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001")
    assert not result.authoritative_eligible
    assert "CANDIDATE_AUTHORITY_CONFLICT" in {finding.code for finding in result.findings}


def test_superseded_requires_explicit_lineage() -> None:
    record, sources = base_record("superseded")
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001")
    assert not result.authoritative_eligible
    assert not result.structural_valid


def test_superseded_record_has_non_authoritative_lineage() -> None:
    record, sources = base_record("superseded")
    old_content = b"old evidence"
    old_ref = ref("qualification_evidence", "old-evidence", "1.0.0", old_content)
    record["supersedes_ref"] = old_ref
    record["provenance"]["source_digests"].append(old_ref["digest"])
    sources[(old_ref["semantic_type"], old_ref["id"], old_ref["version"])] = source(old_ref, old_content)
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001")
    assert not result.authoritative_eligible
    assert result.findings == ()


def test_orphaned_record_requires_reason_and_is_not_authoritative() -> None:
    record, sources = base_record("orphaned")
    record["reason_codes"] = ["NO_AUTHORITY_LINEAGE"]
    result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001")
    assert not result.authoritative_eligible
    assert result.findings == ()


def test_invalid_or_unresolved_record_is_explicitly_non_authoritative() -> None:
    for disposition in ("invalid", "unresolved"):
        record, sources = base_record(disposition)
        record["reason_codes"] = ["SOURCE_NOT_REPRODUCIBLE"]
        result = AssuranceEvidenceLifecycleValidator().validate(record, sources=sources, source_revision="git:fixture-001")
        assert not result.authoritative_eligible
        assert result.findings == ()
