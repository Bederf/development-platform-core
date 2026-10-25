from __future__ import annotations

from copy import deepcopy

import pytest

from adapters.change_surface import ChangeSurfaceVerificationError, canonical_digest, evaluate_change_surface
from adapters.forge_contract_adapter import ForgeContractAdapter, ForgeMappingError


IDENTITY = {
    "project_id": "core",
    "phase_id": "phase-001",
    "work_id": "work-001",
    "request_id": "request-001",
    "attempt_id": "attempt-001",
    "repository": "development-platform-core",
    "baseline": "abc123",
}


def expected(**overrides):
    value = {
        "schema": "change-surface-expected.v1",
        "canonicalization": "json-sort-keys-separators-v1",
        "identity": IDENTITY,
        "authority_ref": "phase-001-authority",
        "expected_paths": ["adapters/change_surface.py"],
        "expected_path_prefixes": [],
        "authorized_expansions": [],
        "expected_components": ["forge"],
        "expected_sensitive_dimensions": [],
        "risk_context": {"risk": "low", "blast_radius": "low"},
        "policies": {"allowed_categories": ["generated", "lockfile", "formatting"]},
    }
    value.update(overrides)
    value["evidence_digest"] = canonical_digest(value)
    return value


def actual(**overrides):
    value = {
        "schema": "change-surface-actual.v1",
        "canonicalization": "json-sort-keys-separators-v1",
        "identity": IDENTITY,
        "revision": "def456",
        "changed_paths": [{"path": "adapters/change_surface.py", "status": "added", "category": "source", "component": "forge"}],
        "affected_components": ["forge"],
        "sensitive_dimensions": [],
        "unknown_dimensions": [],
        "complete": True,
    }
    value.update(overrides)
    value["observation_digest"] = canonical_digest(value)
    return value


def test_expected_surface_passes_and_is_non_authoritative():
    result = evaluate_change_surface(expected=expected(), actual=actual())
    assert result["signal"] == "PASS"
    assert result["authoritative"] is False


def test_forge_mapping_preserves_signal_as_non_authoritative_candidate():
    signal = evaluate_change_surface(expected=expected(), actual=actual())
    candidate = ForgeContractAdapter().change_surface_candidate(signal)
    assert candidate["candidate_type"] == "change_surface_result"
    assert candidate["signal"] == "PASS"
    assert candidate["authoritative"] is False


def test_forge_mapping_rejects_authoritative_signal():
    signal = evaluate_change_surface(expected=expected(), actual=actual())
    signal["authoritative"] = True
    with pytest.raises(ForgeMappingError):
        ForgeContractAdapter().change_surface_candidate(signal)


def test_unexpected_path_requires_review_not_failure():
    result = evaluate_change_surface(expected=expected(), actual=actual(changed_paths=[
        {"path": "adapters/change_surface.py", "status": "added", "category": "source"},
        {"path": "unrelated.py", "status": "modified", "category": "source"},
    ]))
    assert result["signal"] == "REVIEW_REQUIRED"
    assert "unrelated.py" in result["reasons"][0]


def test_authorized_expansion_passes():
    result = evaluate_change_surface(
        expected=expected(authorized_expansions=["tests/test_change_surface.py"]),
        actual=actual(changed_paths=[
            {"path": "adapters/change_surface.py", "status": "added", "category": "source"},
            {"path": "tests/test_change_surface.py", "status": "added", "category": "test"},
        ]),
    )
    assert result["signal"] == "PASS"


@pytest.mark.parametrize("field", ["evidence_digest", "authority_ref"])
def test_missing_expected_evidence_is_incomplete(field):
    value = expected()
    value.pop(field)
    result = evaluate_change_surface(expected=value, actual=actual())
    assert result["signal"] == "INCOMPLETE"


def test_missing_expected_scope_boundary_is_incomplete():
    value = expected()
    value.pop("expected_paths")
    value.pop("expected_components")
    result = evaluate_change_surface(expected=value, actual=actual())
    assert result["signal"] == "INCOMPLETE"


def test_missing_actual_evidence_is_incomplete():
    value = actual()
    value.pop("changed_paths")
    value["observation_digest"] = canonical_digest(value)
    result = evaluate_change_surface(expected=expected(), actual=value)
    assert result["signal"] == "INCOMPLETE"


def test_unknown_surface_is_incomplete():
    result = evaluate_change_surface(expected=expected(), actual=actual(unknown_dimensions=["components"]))
    assert result["signal"] == "INCOMPLETE"


def test_sensitive_change_requires_review():
    result = evaluate_change_surface(expected=expected(), actual=actual(sensitive_dimensions=["authorization"]))
    assert result["signal"] == "REVIEW_REQUIRED"


def test_risk_and_blast_radius_escalation_requires_review():
    result = evaluate_change_surface(
        expected=expected(),
        actual=actual(risk_context={"risk": "high", "blast_radius": "high"}),
    )
    assert result["signal"] == "REVIEW_REQUIRED"


def test_identity_mismatch_is_incomplete():
    identity = deepcopy(IDENTITY)
    identity["baseline"] = "different"
    result = evaluate_change_surface(expected=expected(), actual=actual(identity=identity))
    assert result["signal"] == "INCOMPLETE"


def test_path_traversal_is_rejected_as_incomplete():
    value = actual(changed_paths=[
        {"path": "../outside.py", "status": "modified", "category": "source"},
    ])
    result = evaluate_change_surface(expected=expected(), actual=value)
    assert result["signal"] == "INCOMPLETE"


def test_malformed_input_without_identity_cannot_become_a_signal():
    with pytest.raises(ChangeSurfaceVerificationError):
        evaluate_change_surface(expected={}, actual=actual())


def test_generated_and_lockfile_categories_are_allowed_by_policy():
    result = evaluate_change_surface(
        expected=expected(authorized_expansions=[]),
        actual=actual(changed_paths=[
            {"path": "adapters/change_surface.py", "status": "added", "category": "source"},
            {"path": "poetry.lock", "status": "modified", "category": "lockfile"},
            {"path": "generated/client.py", "status": "added", "category": "generated"},
        ]),
    )
    assert result["signal"] == "PASS"


@pytest.mark.parametrize("which", ["expected", "actual"])
def test_unsupported_input_contract_version_is_incomplete(which):
    value = expected() if which == "expected" else actual()
    value["schema"] = "change-surface-" + ("expected" if which == "expected" else "actual") + ".v2"
    result = evaluate_change_surface(expected=value if which == "expected" else expected(), actual=value if which == "actual" else actual())
    assert result["signal"] == "INCOMPLETE"


def test_actual_digest_rejects_modified_evidence():
    value = actual()
    value["changed_paths"].append({"path": "tampered.py", "status": "added", "category": "source"})
    result = evaluate_change_surface(expected=expected(), actual=value)
    assert result["signal"] == "INCOMPLETE"


def test_expected_digest_rejects_different_evidence():
    value = expected()
    value["expected_paths"].append("different.py")
    result = evaluate_change_surface(expected=value, actual=actual())
    assert result["signal"] == "INCOMPLETE"


@pytest.mark.parametrize("field,value", [
    ("evidence_digest", "sha256:not-a-digest"),
    ("evidence_digest", "md5:" + "0" * 32),
])
def test_malformed_or_unsupported_expected_digest_is_incomplete(field, value):
    record = expected()
    record[field] = value
    result = evaluate_change_surface(expected=record, actual=actual())
    assert result["signal"] == "INCOMPLETE"


def test_unsupported_canonicalization_is_incomplete():
    record = actual()
    record["canonicalization"] = "json-unspecified-v1"
    result = evaluate_change_surface(expected=expected(), actual=record)
    assert result["signal"] == "INCOMPLETE"


def test_equivalent_evidence_has_deterministic_digest():
    first = actual()
    second = {key: first[key] for key in reversed(list(first))}
    second["identity"] = {key: first["identity"][key] for key in reversed(list(first["identity"]))}
    assert canonical_digest(first) == canonical_digest(second)
