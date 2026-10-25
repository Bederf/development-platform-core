import json
import shutil
from pathlib import Path

import pytest

from adapters.phase_authorization import (
    FileAuthorizationStore,
    PhaseAuthorizationError,
    canonical_digest,
    resolve_authorization,
)


SUBJECT = {
    "phase_id": "P040",
    "specification_id": "radix-codex-gsd-projection-verification",
    "specification_version": "1.0.0",
    "specification_hash": "sha256:0862017ccb1682835e9c648b0fb8e4c4d711ab7fd99e59465221469a9928f29e",
}


def _write_record(root, filename, value):
    path = root / filename
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _digest_without_digest(value):
    return canonical_digest(value)


def _fixture_store(tmp_path, *, profile_status="qualified"):
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    source_contracts = Path(__file__).parents[1] / "contracts"
    for filename in (
        "core-qualification-authorization.v2.schema.json",
        "core-qualification-profile.v1.schema.json",
        "dpc-owner-approval.v1.schema.json",
    ):
        shutil.copyfile(source_contracts / filename, contracts / filename)
    assurance = tmp_path / "docs" / "assurance"
    profiles = assurance / "profiles"
    profiles.mkdir(parents=True)

    profile = {
        "schema": "core-qualification-profile.v1",
        "profile_id": "core-qualification-standard",
        "version": "1.0.0",
        "status": profile_status,
        "scope": {
            "scope_type": "core_qualification_only",
            "scope_id": "core-qualification",
            "excluded_authorities": ["runtime", "production_authority"],
        },
        "prerequisites": {
            "required_lineage_types": [
                "authority_binding",
                "dpc-owner-approval",
                "independent-review-request",
                "phase-specification",
            ],
            "phase034_pass_required": False,
        },
        "acceptance_boundary": {
            "authority": "development-platform-core.acceptance-authority",
            "production_authority_granted": False,
        },
    }
    profile["digest"] = _digest_without_digest(profile)
    profile_path = _write_record(profiles, "profile.json", profile)

    authority = {
        "schema": "core-phase-authority-binding.v1",
        "binding_id": "core-phase-authority",
        "version": "1.0.0",
        "issuer": "development-platform-core.phase-authority",
    }
    authority["digest"] = _digest_without_digest(authority)
    authority_path = _write_record(assurance, "authority.json", authority)

    review = {
        "schema": "independent-review-request.v1",
        "request_id": "phase-040-independent-review-request",
        "task_ref": "P040",
        "revision_ref": "phase-040-review-revision",
        "review_package": "phase-040-review",
        "reviewer_ref": "development-platform-core.independent-review",
        "independence_required": True,
        "evidence_refs": ["phase-040-review-evidence"],
    }
    review["digest"] = _digest_without_digest(review)
    review_path = _write_record(assurance, "review.json", review)

    owner = {
        "schema": "dpc-owner-approval.v1",
        "approval_id": "phase-040-owner-approval",
        "decision": "approved",
        "subject": SUBJECT,
        "issuer": "dpc-owner-test",
        "authority": "development-platform-core.owner",
        "scope": "v2-test-only",
        "provenance": {
            "source_refs": ["test-owner-decision"],
            "recording_method": "test-fixture",
        },
        "recorded_at": "2026-10-16T00:00:00Z",
    }
    owner["digest"] = _digest_without_digest(owner)
    owner_path = _write_record(assurance, "owner.json", owner)

    refs = {
        "profile": {
            "semantic_type": "qualification-profile",
            "id": profile["profile_id"],
            "version": profile["version"],
            "digest": profile["digest"],
        },
        "authority": {
            "semantic_type": "authority_binding",
            "id": authority["binding_id"],
            "version": authority["version"],
            "digest": authority["digest"],
        },
        "review": {
            "semantic_type": "independent-review-request",
            "id": review["request_id"],
            "version": "1.0.0",
            "digest": review["digest"],
        },
        "owner": {
            "semantic_type": "dpc-owner-approval",
            "id": owner["approval_id"],
            "version": "1.0.0",
            "digest": owner["digest"],
        },
    }
    authorization = {
        "schema": "core-qualification-authorization.v2",
        "authorization_id": "phase-040-authorization-v2",
        "decision": "approved",
        "subject": SUBJECT,
        "profile_ref": refs["profile"],
        "scope": profile["scope"],
        "issuer": "development-platform-core.phase-authority",
        "owner_approval_ref": refs["owner"],
        "authority_binding": refs["authority"],
        "review_request_ref": refs["review"],
        "issued_at": "2026-10-16T00:00:00Z",
        "valid_until": None,
        "lineage": [
            {
                "semantic_type": "phase-specification",
                "id": SUBJECT["specification_id"],
                "version": SUBJECT["specification_version"],
                "digest": SUBJECT["specification_hash"],
            },
            refs["review"],
        ],
    }
    authorization["digest"] = _digest_without_digest(authorization)
    authorization_path = _write_record(assurance, "authorization.json", authorization)

    entries = [
        {"id": refs["profile"]["id"], "kind": "qualification_profile", "path": str(profile_path.relative_to(tmp_path)), "digest": refs["profile"]["digest"]},
        {"id": refs["authority"]["id"], "kind": "authority_binding", "path": str(authority_path.relative_to(tmp_path)), "digest": refs["authority"]["digest"]},
        {"id": refs["review"]["id"], "kind": "review_request", "path": str(review_path.relative_to(tmp_path)), "digest": refs["review"]["digest"]},
        {"id": refs["owner"]["id"], "kind": "owner_approval", "path": str(owner_path.relative_to(tmp_path)), "digest": refs["owner"]["digest"]},
        {"id": authorization["authorization_id"], "kind": "authorization", "path": str(authorization_path.relative_to(tmp_path)), "digest": authorization["digest"]},
    ]
    index = {"schema": "core-authorization-index.v1", "index_id": "test-index", "entries": entries}
    index["digest"] = _digest_without_digest(index)
    _write_record(assurance, "CORE-AUTHORIZATION-INDEX-v1.json", index)
    return FileAuthorizationStore(root=tmp_path, test_only=True), authorization["authorization_id"]


def test_v2_authorization_resolves_through_governed_profile(tmp_path):
    store, authorization_id = _fixture_store(tmp_path)
    resolved = resolve_authorization(authorization_id, subject=SUBJECT, store=store)
    assert resolved["schema"] == "core-qualification-authorization.v2"
    assert resolved["profile_ref"]["id"] == "core-qualification-standard"


def test_v2_rejects_unqualified_profile(tmp_path):
    store, authorization_id = _fixture_store(tmp_path, profile_status="retired")
    with pytest.raises(PhaseAuthorizationError, match="profile is not qualified"):
        resolve_authorization(authorization_id, subject=SUBJECT, store=store)


def test_v2_rejects_missing_owner_lineage(tmp_path):
    store, authorization_id = _fixture_store(tmp_path)
    index_path = tmp_path / "docs" / "assurance" / "CORE-AUTHORIZATION-INDEX-v1.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["entries"] = [entry for entry in index["entries"] if entry["kind"] != "owner_approval"]
    index["digest"] = canonical_digest(index)
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(PhaseAuthorizationError, match="reference is missing or ambiguous"):
        resolve_authorization(authorization_id, subject=SUBJECT, store=store)
