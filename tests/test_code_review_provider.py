from __future__ import annotations

import pytest

from adapters.code_review_context import ReviewContextError, build_review_package
from adapters.code_review_provider import CodeReviewProviderAdapter, CodeReviewProviderError


def package():
    return build_review_package(
        attempt_ref="attempt-002",
        specification="Implement the governed review path.",
        diff="diff --git a/example.py b/example.py",
        changed_files=["example.py"],
        tests=[{"kind": "verification", "ref": "tests:002"}],
        architecture_refs=["adr:review-boundary"],
        classification={"touches_backend": True},
    )


def valid_result():
    return {
        "schema": "code-review-result.v1",
        "review_id": "review-002",
        "attempt_ref": "attempt-002",
        "independence": "independent",
        "classification": {"touches_backend": True},
        "providers": {"considered": ["reviewer"], "selected": ["reviewer"], "skipped": []},
        "findings": [],
        "disposition": "PASS",
        "evidence": [
            {"kind": "specification", "ref": "phase:002"},
            {"kind": "diff", "ref": "git:attempt-002"},
            {"kind": "verification", "ref": "tests:002"},
        ],
        "generated_at": "2026-09-02T10:00:00+00:00",
    }


def test_context_is_bounded_and_provider_receives_no_repository_handle() -> None:
    received = {}
    result = valid_result()

    def provider(context):
        received.update(context)
        return result

    returned = CodeReviewProviderAdapter(provider).review(package())
    assert returned == result
    assert received["schema"] == "code-review-package.v1"
    assert received["changed_files"] == ["example.py"]
    assert "repository" not in received
    assert "write" not in received


def test_invalid_provider_result_is_rejected() -> None:
    with pytest.raises(CodeReviewProviderError, match="invalid review result"):
        CodeReviewProviderAdapter(lambda _context: {"disposition": "PASS"}).review(package())


def test_missing_review_context_is_rejected() -> None:
    with pytest.raises(ReviewContextError, match="specification is required"):
        build_review_package(attempt_ref="attempt", specification="", diff="diff", changed_files=["x.py"])
