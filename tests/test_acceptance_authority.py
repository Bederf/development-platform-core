from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from adapters.acceptance_authority import (
    AcceptanceAuthority,
    AcceptanceAuthorityError,
    AcceptanceConflict,
)
from adapters.phase_authorization import (
    FileAuthorizationStore,
    canonical_digest,
)


def artifact(ref, kind, stage, producer):
    return {
        "artifact_ref": ref,
        "kind": kind,
        "stage": stage,
        "artifact_version": "1.0.0",
        "digest": f"sha256:{ref}",
        "producer": producer,
        "supersedes_ref": None,
        "created_at": "2026-09-22T00:00:00+00:00",
    }


def workflow():
    value = {
        "schema": "development-workflow.v1",
        "workflow_id": "workflow-302c",
        "intent_ref": "intent-302c",
        "status": "ACTIVE",
        "current_stage": "CONVERGENCE",
        "artifacts": [
            artifact("intent-302c", "intent", "INTENT", "gsd"),
            artifact(
                "cloudflare-security-audit-core-qualification-pilot",
                "specification",
                "SPECIFICATION",
                "gsd",
            ),
            artifact(
                "implementation-rev-7", "implementation", "IMPLEMENTATION", "agent"
            ),
            artifact(
                "verification-7", "verification", "VERIFICATION", "independent-verifier"
            ),
            artifact("convergence-7", "convergence", "CONVERGENCE", "gsd"),
        ],
        "gates": [],
        "transitions": [],
        "verification_refs": ["verification-7"],
        "evidence_refs": [
            "spec-evidence",
            "diff-evidence",
            "test-evidence",
            "verification-7",
        ],
        "acceptance_ref": None,
        "created_at": "2026-09-22T00:00:00+00:00",
        "updated_at": "2026-09-22T00:00:00+00:00",
    }
    value["artifacts"][1]["digest"] = (
        "sha256:085caadd6c671c8558559672836d2e845608b8ca41561e7f70be408a60139435"
    )
    return value


def review_cycle():
    return {
        "outcome": "PASS",
        "next_action": "forge_verify",
        "status": "PASSED",
        "review_result_ref": "review-rev-7",
    }


def review_result():
    return {
        "schema": "code-review-result.v1",
        "review_id": "review-rev-7",
        "attempt_ref": "implementation-rev-7",
        "independence": "independent",
        "classification": {},
        "providers": {
            "considered": ["omniroute"],
            "selected": ["omniroute"],
            "skipped": [],
        },
        "findings": [],
        "disposition": "PASS",
        "evidence": [
            {"kind": "specification", "ref": "spec-evidence"},
            {"kind": "diff", "ref": "diff-evidence"},
            {"kind": "verification", "ref": "test-evidence"},
        ],
        "generated_at": "2026-09-22T00:00:00+00:00",
    }


def typed_ref(identifier: str, semantic_type: str = "artifact"):
    content = {"id": identifier, "semantic_type": semantic_type}
    digest = hashlib.sha256(
        json.dumps({"content": content}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "semantic_type": semantic_type,
        "id": identifier,
        "version": "1.0.0",
        "digest": "sha256:" + digest,
        "content": content,
    }


def forge_evidence():
    refs = [
        typed_ref("forge-check-evidence"),
        typed_ref("forge-lineage", "provenance"),
        typed_ref("phase-034-independent-review-request", "independent-review-request"),
    ]
    artifact_content = {"result": "passed", "artifact": "forge-output"}
    artifact_digest = hashlib.sha256(
        json.dumps(
            {"content": artifact_content}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    evidence = {
        "schema": "forge-qualification-evidence.v1",
        "phase_specification_ref": "cloudflare-security-audit-core-qualification-pilot",
        "verification_attempt_id": "accept-attempt-1",
        "source_revision": "implementation-rev-7",
        "status": "PASSED",
        "checks": [
            {"check_id": "schema", "status": "PASSED", "evidence_refs": [refs[0]]}
        ],
        "artifacts": [
            {
                "artifact_ref": "forge-output",
                "digest": "sha256:" + artifact_digest,
                "source_revision": "implementation-rev-7",
                "content": artifact_content,
            }
        ],
        "lineage": [refs[1], refs[2]],
        "completeness": "COMPLETE",
        "provenance": {
            "issuer": "test-independent-verifier",
            "provider": "omniroute",
            "tool": {"name": "forge-qualification-fixture", "version": "1.0.0"},
            "review_request_ref": "phase-034-independent-review-request",
            "independence": True,
        },
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["digest"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return refs, evidence


def accept(authority, **changes):
    if authority.authorization_store is None:
        root = Path(__file__).parents[1]
        authorization = json.loads(
            (
                root
                / "docs/assurance/PHASE-033-CORE-QUALIFICATION-AUTHORIZATION-v1.json"
            ).read_text()
        )
        authorization["decision"] = "approved"
        authorization["digest"] = canonical_digest(authorization)
        authorization_path = authority.path.parent / "test-authorization.json"
        authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
        lineage = {}
        for name in (
            "CORE-PHASE-AUTHORITY-BINDING-v1.json",
            "PHASE-034-INDEPENDENT-REVIEW-REQUEST-v1.json",
        ):
            value = json.loads((root / "docs/assurance" / name).read_text())
            identifier = value.get("binding_id", value.get("request_id"))
            lineage[identifier] = value
        authority.authorization_store = FileAuthorizationStore(
            authorization_path,
            lineage_records=lineage,
            index_path=root
            / "tests/fixtures/phase034/CORE-AUTHORIZATION-INDEX-PASS.json",
            test_only=True,
        )
    refs, forge = forge_evidence()
    values = {
        "workflow": workflow(),
        "approved_specification_ref": "cloudflare-security-audit-core-qualification-pilot",
        "implementation_revision_ref": "implementation-rev-7",
        "approved_requirement_refs": ["R1", "R2"],
        "requirement_evaluations": [
            {
                "requirement_ref": "R1",
                "status": "satisfied",
                "evidence_refs": ["test-evidence"],
            },
            {
                "requirement_ref": "R2",
                "status": "satisfied",
                "evidence_refs": ["verification-7"],
            },
        ],
        "available_evidence": [
            "spec-evidence",
            "diff-evidence",
            "test-evidence",
            "verification-7",
            "convergence-7",
        ],
        "review_cycle": review_cycle(),
        "independent_review_result": review_result(),
        "focused_tests_passed": True,
        "live_verification_passed": False,
        "qualification_evidence_passed": True,
        "evidence_integrity_verified": True,
        "before_after_evidence_present": True,
        "unresolved_blockers": 0,
        "forge_status": "PASSED",
        "authorization_ref": "phase-033-core-qualification-authorization",
        "phase_specification_binding": {
            "phase_id": "P033",
            "specification_ref": "cloudflare-security-audit-core-qualification-pilot",
            "specification_id": "cloudflare-security-audit-core-qualification-pilot",
            "specification_version": "1.0.0",
            "specification_hash": "sha256:085caadd6c671c8558559672836d2e845608b8ca41561e7f70be408a60139435",
            "forge_required": True,
            "verification_mode": "qualification",
        },
        "verification_mode": "qualification",
        "forge_evidence": forge,
        "typed_evidence_refs": refs,
        "convergence_result": {
            "report_type": "convergence",
            "requirements_complete": True,
            "evidence_refs": ["convergence-7"],
        },
        "acceptance_attempt_id": "accept-attempt-1",
        "acceptance_ref": "acceptance-workflow-302c-1",
    }
    values.update(changes)
    return authority.accept(**values)


def test_acceptance_requires_complete_closure(tmp_path):
    authority = AcceptanceAuthority(tmp_path / "workflow.json")
    with pytest.raises(AcceptanceAuthorityError, match="requirements are not closed"):
        accept(authority, requirement_evaluations=[])
    assert not (tmp_path / "workflow.json").exists()


def test_local_or_review_pass_does_not_persist_acceptance(tmp_path):
    authority = AcceptanceAuthority(tmp_path / "workflow.json")
    with pytest.raises(AcceptanceAuthorityError, match="independent review"):
        accept(authority, independent_review_result=None)
    assert not (tmp_path / "workflow.json").exists()


def test_acceptance_is_atomic_and_idempotent(tmp_path):
    path = tmp_path / "workflow.json"
    authority = AcceptanceAuthority(path)
    first = accept(authority)
    second = accept(authority)
    assert first == second
    assert json.loads(path.read_text()) == first

    with pytest.raises(AcceptanceConflict):
        accept(authority, acceptance_ref="different-acceptance")


def test_convergence_evidence_is_required(tmp_path):
    authority = AcceptanceAuthority(tmp_path / "workflow.json")
    with pytest.raises(AcceptanceAuthorityError, match="convergence requires evidence"):
        accept(
            authority,
            convergence_result={
                "report_type": "convergence",
                "requirements_complete": True,
                "evidence_refs": [],
            },
        )


def test_accepted_workflow_cannot_be_downgraded(tmp_path):
    authority = AcceptanceAuthority(tmp_path / "workflow.json")
    accepted = accept(authority)
    changed = copy.deepcopy(accepted)
    changed["status"] = "ACTIVE"
    with pytest.raises(AcceptanceAuthorityError, match="already accepted"):
        authority.accept(
            changed,
            approved_specification_ref="spec-302c-v2.1.1",
            implementation_revision_ref="implementation-rev-7",
            approved_requirement_refs=["R1", "R2"],
            requirement_evaluations=[],
            available_evidence=[],
            review_cycle=review_cycle(),
            independent_review_result=review_result(),
            focused_tests_passed=True,
            live_verification_passed=True,
            evidence_integrity_verified=True,
            before_after_evidence_present=True,
            unresolved_blockers=0,
            forge_status="PASSED",
            convergence_result={
                "report_type": "convergence",
                "requirements_complete": True,
                "evidence_refs": ["convergence-7"],
            },
            acceptance_attempt_id="accept-attempt-2",
            acceptance_ref="acceptance-2",
        )
