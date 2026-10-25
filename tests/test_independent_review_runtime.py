from __future__ import annotations

import pytest

import scripts.independent_review_runtime as runtime
from scripts.independent_review_runtime import execute


def payload():
    return {
        "request": {
            "schema": "independent-review-request.v1",
            "request_id": "request-runtime-001",
            "task_ref": "task-001",
            "revision_ref": "revision-001",
            "review_package": "package-001",
            "reviewer_ref": "development-platform-code-reviewer",
            "independence_required": True,
            "evidence_refs": ["spec-001", "diff-001", "tests-001"],
        },
        "package": {
            "attempt_ref": "revision-001",
            "specification": "Implement the review runtime.",
            "diff": "diff --git a/example.py b/example.py",
            "changed_files": ["example.py"],
            "tests": [{"kind": "verification", "ref": "tests-001"}],
            "architecture_refs": [],
            "classification": {"touches_backend": True},
        },
        "implementation_context_id": "coding-context",
        "review_context_id": "review-context",
        "cycle_number": 1,
    }


def test_runtime_dispatches_fake_provider_without_credentials(monkeypatch):
    monkeypatch.setenv("CODE_REVIEW_PROVIDER", "fake")
    result = execute(payload())
    assert result["review_result"]["disposition"] == "PASS"
    assert result["review_cycle"]["next_action"] == "forge_verify"


def test_runtime_does_not_require_or_emit_provider_secret(monkeypatch):
    monkeypatch.setenv("CODE_REVIEW_PROVIDER", "fake")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-must-not-be-emitted")
    result = execute(payload())
    assert "GEMINI_API_KEY" not in str(result)
    assert "secret-must-not-be-emitted" not in str(result)


def test_runtime_emits_fresh_review_observation(monkeypatch):
    monkeypatch.setenv("CODE_REVIEW_PROVIDER", "fake")
    first = execute(payload())
    second = execute(payload())
    first_observation = first["review_observation"]
    second_observation = second["review_observation"]
    assert first_observation["fresh_request"] is True
    assert second_observation["fresh_request"] is True
    assert first_observation["provider_request_id"] != second_observation["provider_request_id"]
    assert first_observation["schema_version"] == "code-review-result.v1"
    assert first_observation["raw_provider_status"] == "FAKE_OR_IN_PROCESS"


def test_non_agy_provider_routes_are_removed():
    with pytest.raises(runtime.IndependentReviewError):
        runtime.resolve_provider("openai")
    with pytest.raises(runtime.IndependentReviewError):
        runtime.resolve_provider("dsh-tui")
