from __future__ import annotations

import copy
from pathlib import Path

import pytest

from adapters.evidence_binding import (
    EvidenceBindingError,
    EvidenceBindingStore,
    build_binding,
    digest_for,
    reconcile_historical,
    validate_binding,
)


def source_records() -> tuple[dict, dict, dict, str, dict]:
    request = {
        "schema": "independent-review-request.v1",
        "request_id": "request-001",
        "task_ref": "phase-900",
        "revision_ref": "implementation-001",
        "review_package": "package-001",
        "reviewer_ref": "core-independent-reviewer",
        "independence_required": True,
        "evidence_refs": ["spec-001", "diff-001", "tests-001"],
    }
    result = {
        "schema": "code-review-result.v1",
        "review_id": "review-001",
        "attempt_ref": "implementation-001",
        "independence": "independent",
        "providers": {"considered": ["omniroute"], "selected": ["omniroute"], "skipped": []},
        "findings": [],
        "disposition": "PASS",
        "evidence": [{"kind": "spec", "ref": "spec-001"}, {"kind": "diff", "ref": "diff-001"}, {"kind": "tests", "ref": "tests-001"}],
        "classification": {},
        "generated_at": "2026-10-08T10:00:00+00:00",
    }
    cycle = {
        "schema": "review-cycle.v1",
        "cycle_id": "cycle-001",
        "task_ref": "phase-900",
        "revision_ref": "implementation-001",
        "cycle_number": 1,
        "max_cycles": 3,
        "prior_cycle_ref": None,
        "review_result_ref": "review-001",
        "finding_refs": [],
        "outcome": "PASS",
        "next_action": "forge_verify",
        "next_revision_ref": None,
        "verification_ref": None,
        "evidence_refs": ["spec-001", "diff-001", "tests-001"],
        "status": "PASSED",
        "created_at": "2026-10-08T10:01:00+00:00",
    }
    raw = "canonical raw provider response"
    provider = {"provider_ref": "omniroute", "model": "model-1", "provider_request_id": "provider-001", "provider_invocation_id": "call-001", "reviewer_ref": "core-independent-reviewer"}
    return request, result, cycle, raw, provider


def make_binding(raw: str | None = None) -> tuple[dict, dict, dict, dict, str, dict]:
    request, result, cycle, original_raw, provider = source_records()
    raw = original_raw if raw is None else raw
    binding = build_binding(
        request, result, cycle,
        raw_evidence=raw,
        raw_evidence_ref="provider-001/raw-response.txt",
        implementation_context_id="implementation-context-001",
        reviewer_context_id="review-context-001",
        core_invocation_id="core-invocation-001",
        provider=provider,
        policy_ref="review-lifecycle-policy",
        binding_id="binding-001",
    )
    return binding, request, result, cycle, raw, provider


def test_valid_binding_is_core_owned_and_digest_bound() -> None:
    binding, request, result, cycle, raw, _ = make_binding()
    assert binding["schema"] == "evidence-binding.v1"
    assert binding["lifecycle"]["retention_basis"] == "lifecycle-bound"
    validate_binding(binding, evidence={"request": request, "raw": raw, "review_result": result, "review_cycle": cycle})


def test_mismatched_identity_and_digest_fail_closed() -> None:
    binding, request, result, cycle, raw, _ = make_binding()
    altered = copy.deepcopy(result)
    altered["review_id"] = "review-other"
    with pytest.raises(EvidenceBindingError, match="review result digest mismatch"):
        validate_binding(binding, evidence={"request": request, "raw": raw, "review_result": altered, "review_cycle": cycle})
    altered_binding = copy.deepcopy(binding)
    altered_binding["review"]["reviewer_context_id"] = altered_binding["subject"]["implementation_context_id"]
    altered_binding["binding_digest"] = digest_for({key: item for key, item in altered_binding.items() if key != "binding_digest"})
    with pytest.raises(EvidenceBindingError, match="contexts must differ"):
        validate_binding(altered_binding)


def test_referenced_review_contracts_are_validated() -> None:
    request, result, cycle, raw, provider = source_records()
    result["disposition"] = "NOT_A_REVIEW_RESULT"
    with pytest.raises(EvidenceBindingError, match="code-review-result"):
        build_binding(
            request, result, cycle, raw_evidence=raw, raw_evidence_ref="raw.txt",
            implementation_context_id="impl-context", reviewer_context_id="review-context",
            core_invocation_id="core-invocation", provider=provider, policy_ref="policy",
        )


def test_tampered_raw_evidence_fails_closed() -> None:
    binding, request, result, cycle, _, _ = make_binding()
    with pytest.raises(EvidenceBindingError, match="raw evidence digest mismatch"):
        validate_binding(binding, evidence={"request": request, "raw": "tampered", "review_result": result, "review_cycle": cycle})


def test_provider_ids_may_be_missing_but_core_invocation_is_required() -> None:
    request, result, cycle, raw, provider = source_records()
    provider["provider_request_id"] = None
    provider["provider_invocation_id"] = None
    binding = build_binding(
        request, result, cycle, raw_evidence=raw, raw_evidence_ref="raw.txt",
        implementation_context_id="impl-context", reviewer_context_id="review-context",
        core_invocation_id="core-invocation", provider=provider, policy_ref="policy", binding_id="binding-optional-provider-ids",
    )
    assert binding["review"]["provider"]["provider_request_id"] is None
    with pytest.raises(EvidenceBindingError, match="Core invocation"):
        build_binding(request, result, cycle, raw_evidence=raw, raw_evidence_ref="raw.txt", implementation_context_id="impl-context", reviewer_context_id="review-context", core_invocation_id="", provider=provider, policy_ref="policy")


def test_lifecycle_policy_reference_is_required() -> None:
    request, result, cycle, raw, provider = source_records()
    with pytest.raises(EvidenceBindingError, match="policy reference"):
        build_binding(
            request, result, cycle, raw_evidence=raw, raw_evidence_ref="raw.txt",
            implementation_context_id="impl-context", reviewer_context_id="review-context",
            core_invocation_id="core-invocation", provider=provider, policy_ref="",
        )


def test_two_stage_lifecycle_requires_eligibility_before_deletion(tmp_path: Path) -> None:
    binding, *_ = make_binding()
    store = EvidenceBindingStore(tmp_path / "bindings")
    store.persist(binding)
    with pytest.raises(EvidenceBindingError, match="prior eligibility"):
        store.authorize_deletion("binding-001", authority_ref="owner-auth")
    with pytest.raises(EvidenceBindingError, match="not eligible"):
        store.evaluate_eligibility("binding-001", lifecycle_complete=False, evidence_still_required=False, evaluated_by="owner", eligibility_ref="eligible-001")
    eligible = store.evaluate_eligibility("binding-001", lifecycle_complete=True, evidence_still_required=False, evaluated_by="owner", eligibility_ref="eligible-001")
    assert eligible["binding_status"] == "ELIGIBLE_FOR_DISPOSITION"
    authorized = store.authorize_deletion("binding-001", authority_ref="delete-auth-001", authorized_by="owner")
    assert authorized["binding_status"] == "DELETION_AUTHORIZED"


def test_deletion_requires_matching_raw_digest_and_leaves_receipt(tmp_path: Path) -> None:
    binding, *_ = make_binding()
    raw_root = tmp_path / "raw"
    (raw_root / "provider-001").mkdir(parents=True)
    (raw_root / "provider-001" / "raw-response.txt").write_text("canonical raw provider response", encoding="utf-8")
    store = EvidenceBindingStore(tmp_path / "bindings")
    store.persist(binding)
    store.evaluate_eligibility("binding-001", lifecycle_complete=True, evidence_still_required=False, evaluated_by="owner", eligibility_ref="eligible-001")
    store.authorize_deletion("binding-001", authority_ref="delete-auth-001", authorized_by="owner")
    deleted = store.delete_raw_evidence("binding-001", evidence_root=raw_root, authorized_by="owner")
    assert deleted["binding_status"] == "DELETED"
    assert deleted["lifecycle"]["deletion_receipt"]["authorization_ref"] == "delete-auth-001"
    assert not (raw_root / "provider-001" / "raw-response.txt").exists()


def test_deletion_cannot_use_altered_raw_evidence(tmp_path: Path) -> None:
    binding, *_ = make_binding()
    raw_root = tmp_path / "raw"
    (raw_root / "provider-001").mkdir(parents=True)
    (raw_root / "provider-001" / "raw-response.txt").write_text("altered", encoding="utf-8")
    store = EvidenceBindingStore(tmp_path / "bindings")
    store.persist(binding)
    store.evaluate_eligibility("binding-001", lifecycle_complete=True, evidence_still_required=False, evaluated_by="owner", eligibility_ref="eligible-001")
    store.authorize_deletion("binding-001", authority_ref="delete-auth-001", authorized_by="owner")
    with pytest.raises(EvidenceBindingError, match="digest"):
        store.delete_raw_evidence("binding-001", evidence_root=raw_root, authorized_by="owner")


def test_historical_reconciliation_does_not_invent_missing_provenance() -> None:
    record = reconcile_historical(source_ref="legacy/provider-request-001", fields={"request_id": "legacy-request"}, relevant=True)
    assert record["record_type"] == "historical_reconciliation"
    assert record["binding_status"] == "PARTIALLY_BOUND"
    assert "reviewer_context_id" in record["historical_reconciliation"]["missing_fields"]
    assert record["evidence"]["raw"] is None


def test_unbound_historical_record_is_not_lifecycle_deletable() -> None:
    record = reconcile_historical(source_ref="legacy/unknown", fields={}, relevant=False)
    assert record["binding_status"] == "UNBOUND_INSUFFICIENT"
    assert record["lifecycle"]["state"] == "ACTIVE"
