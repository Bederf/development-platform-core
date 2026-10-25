from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from adapters.code_review import CodeReviewError, FakeCodeReviewAgent


ROOT = Path(__file__).parents[1]


def valid_frame(**overrides: object) -> dict[str, object]:
    frame: dict[str, object] = {
        "frame_id": "review-frame-001",
        "attempt_ref": "attempt-001",
        "review_id": "review-001",
        "independence": "independent",
        "classification": {"touches_frontend": False},
    }
    frame.update(overrides)
    return frame


def evidence() -> list[dict[str, str]]:
    return [
        {"kind": "specification", "ref": "phase:001"},
        {"kind": "diff", "ref": "git:attempt-001"},
        {"kind": "verification", "ref": "tests:attempt-001"},
    ]


def validate(result: dict) -> None:
    schema = json.loads((ROOT / "contracts/code-review-result.v1.schema.json").read_text())
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(result))
    assert not errors, [error.message for error in errors]


def test_fake_provider_returns_schema_valid_pass() -> None:
    result = FakeCodeReviewAgent().review(valid_frame(), evidence=evidence())
    validate(result)
    assert result["disposition"] == "PASS"


def test_blocking_finding_requires_changes() -> None:
    finding = {
        "id": "finding-001", "severity": "blocker", "confidence": "high",
        "title": "Missing acceptance criterion", "description": "Required behavior is absent.",
        "category": "correctness", "evidence_ref": "diff:file:1",
        "recommendation": "Implement the missing behavior.", "source": "fake",
    }
    result = FakeCodeReviewAgent().review(valid_frame(), findings=[finding], evidence=evidence())
    validate(result)
    assert result["disposition"] == "CHANGES_REQUIRED"


def test_self_review_cannot_pass() -> None:
    result = FakeCodeReviewAgent().review(valid_frame(independence="self_review"), evidence=evidence())
    validate(result)
    assert result["disposition"] == "BLOCKED"
    assert any(item["id"] == "review.independence.self-review" for item in result["findings"])


def test_insufficient_evidence_is_incomplete() -> None:
    result = FakeCodeReviewAgent().review(valid_frame(), evidence=evidence()[:2])
    validate(result)
    assert result["disposition"] == "INCOMPLETE_REVIEW"


def test_invalid_finding_is_rejected() -> None:
    try:
        FakeCodeReviewAgent().review(valid_frame(), findings=[{"id": "bad"}], evidence=evidence())
    except CodeReviewError as exc:
        assert "missing fields" in str(exc)
    else:
        raise AssertionError("invalid finding was accepted")
