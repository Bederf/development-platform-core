from __future__ import annotations

from pathlib import Path

import pytest

from adapters.code_review import FakeCodeReviewAgent
from adapters.code_review_context import build_review_package
from adapters.independent_review import IndependentReviewAdapter, IndependentReviewError


def package():
    return build_review_package(
        attempt_ref="revision-001",
        specification="Implement the independent reviewer bridge.",
        diff="diff --git a/adapters/independent_review.py b/adapters/independent_review.py",
        changed_files=["adapters/independent_review.py"],
        tests=[{"kind": "verification", "ref": "tests:review"}],
    )


def request():
    return IndependentReviewAdapter.make_request(
        request_id="request-001",
        task_ref="task-001",
        revision_ref="revision-001",
        package_ref="package-001",
        evidence_refs=["spec-001", "diff-001", "tests-001"],
    )


def test_fresh_context_review_returns_result_and_cycle():
    fake = FakeCodeReviewAgent()

    def provider(context):
        return fake.review(
            {"attempt_ref": context["attempt_ref"], "independence": "independent"},
            evidence=[
                {"kind": "specification", "ref": "spec-001"},
                {"kind": "diff", "ref": "diff-001"},
                {"kind": "verification", "ref": "tests-001"},
            ],
        )

    adapter = IndependentReviewAdapter(provider, review_context_id="review-session")
    outcome = adapter.review(
        request(), package(), implementation_context_id="coding-session", cycle_number=1
    )
    assert outcome["review_result"]["disposition"] == "PASS"
    assert outcome["review_cycle"]["outcome"] == "PASS"
    assert outcome["review_cycle"]["next_action"] == "forge_verify"


def test_same_context_is_rejected_as_self_review():
    adapter = IndependentReviewAdapter(FakeCodeReviewAgent().review, review_context_id="coding-session")
    with pytest.raises(IndependentReviewError, match="contexts must be separate"):
        adapter.review(request(), package(), implementation_context_id="coding-session", cycle_number=1)


def test_provider_failure_is_blocked_and_never_passes():
    def failing_provider(_context):
        raise RuntimeError("provider unavailable")

    adapter = IndependentReviewAdapter(failing_provider, review_context_id="review-session")
    outcome = adapter.review(
        request(), package(), implementation_context_id="coding-session", cycle_number=1
    )
    assert outcome["review_result"]["disposition"] == "BLOCKED"
    assert outcome["review_cycle"]["status"] == "ESCALATED"
    assert outcome["review_cycle"]["next_action"] == "escalate"


def test_retry_limit_is_bounded_and_changes_provider_request_identity():
    calls = []

    def provider(context):
        calls.append(context["_runtime"]["provider_request_id"])
        raise RuntimeError("provider unavailable")

    adapter = IndependentReviewAdapter(provider, review_context_id="review-session")
    outcome = adapter.review(
        request(),
        package(),
        implementation_context_id="coding-session",
        cycle_number=1,
        runtime_context={"provider_request_id": "provider-request-001"},
        max_retries=2,
    )
    assert outcome["review_result"]["disposition"] == "BLOCKED"
    assert len(calls) == 3
    assert len(set(calls)) == 3


def test_malformed_provider_result_is_blocked_and_never_passes():
    adapter = IndependentReviewAdapter(lambda _context: {"disposition": "PASS"}, review_context_id="review-session")
    outcome = adapter.review(
        request(), package(), implementation_context_id="coding-session", cycle_number=1
    )
    assert outcome["review_result"]["disposition"] == "BLOCKED"
    assert outcome["review_cycle"]["outcome"] == "ESCALATED"


def test_evidence_aggregator_cannot_pass_as_independent_reviewer():
    fake = FakeCodeReviewAgent()

    def provider(context):
        result = fake.review(
            {"attempt_ref": context["attempt_ref"], "independence": "independent"},
            evidence=[
                {"kind": "specification", "ref": "spec-001"},
                {"kind": "diff", "ref": "diff-001"},
                {"kind": "verification", "ref": "tests-001"},
            ],
        )
        result["providers"] = {
            "considered": ["evidence_reviewer"],
            "selected": ["evidence_reviewer"],
            "skipped": [],
        }
        return result

    adapter = IndependentReviewAdapter(provider, review_context_id="review-session")
    outcome = adapter.review(
        request(), package(), implementation_context_id="coding-session", cycle_number=1
    )
    assert outcome["review_result"]["disposition"] == "BLOCKED"
    assert outcome["review_cycle"]["outcome"] == "ESCALATED"


def test_incomplete_evidence_cannot_pass_as_independent_review():
    fake = FakeCodeReviewAgent()

    def provider(context):
        return fake.review(
            {"attempt_ref": context["attempt_ref"], "independence": "independent"},
            evidence=[{"kind": "diff", "ref": "diff-001"}],
        )

    adapter = IndependentReviewAdapter(provider, review_context_id="review-session")
    outcome = adapter.review(
        request(), package(), implementation_context_id="coding-session", cycle_number=1
    )
    assert outcome["review_result"]["disposition"] == "BLOCKED"
    assert outcome["review_cycle"]["outcome"] == "ESCALATED"


def test_review_evidence_must_match_the_request():
    fake = FakeCodeReviewAgent()

    def provider(context):
        return fake.review(
            {"attempt_ref": context["attempt_ref"], "independence": "independent"},
            evidence=[
                {"kind": "specification", "ref": "other-spec"},
                {"kind": "diff", "ref": "diff-001"},
                {"kind": "verification", "ref": "tests-001"},
            ],
        )

    adapter = IndependentReviewAdapter(provider, review_context_id="review-session")
    outcome = adapter.review(
        request(), package(), implementation_context_id="coding-session", cycle_number=1
    )
    assert outcome["review_result"]["disposition"] == "BLOCKED"
    assert outcome["review_cycle"]["outcome"] == "ESCALATED"


def test_stale_revision_cannot_be_promoted():
    fake = FakeCodeReviewAgent()

    def provider(_context):
        return fake.review(
            {"attempt_ref": "revision-old", "independence": "independent"},
            evidence=[
                {"kind": "specification", "ref": "spec-001"},
                {"kind": "diff", "ref": "diff-001"},
                {"kind": "verification", "ref": "tests-001"},
            ],
        )

    adapter = IndependentReviewAdapter(provider, review_context_id="review-session")
    outcome = adapter.review(
        request(), package(), implementation_context_id="coding-session", cycle_number=1
    )
    assert outcome["review_result"]["disposition"] == "BLOCKED"
    assert outcome["review_cycle"]["outcome"] == "ESCALATED"


def test_malformed_request_fails_closed_before_provider_call():
    called = False

    def provider(_context):
        nonlocal called
        called = True
        return {}

    adapter = IndependentReviewAdapter(provider, review_context_id="review-session")
    invalid = request()
    invalid["independence_required"] = False
    with pytest.raises(IndependentReviewError, match="invalid independent-review request"):
        adapter.review(invalid, package(), implementation_context_id="coding-session", cycle_number=1)
    assert called is False


def test_configured_core_lifecycle_persists_evidence_binding(tmp_path: Path):
    fake = FakeCodeReviewAgent()
    raw_root = tmp_path / "raw"
    raw_file = raw_root / "provider-request-001" / "raw-response.txt"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text("provider raw response", encoding="utf-8")

    class ObservedProvider:
        last_observation = {
            "provider": "fake",
            "model": "fake-model",
            "provider_request_id": "provider-request-001",
            "omniroute_call_id": "provider-call-001",
            "generation_id": None,
            "raw_provider_response": "provider raw response",
            "raw_response_ref": str(raw_file),
        }

        def __call__(self, context):
            return fake.review(
                {"attempt_ref": context["attempt_ref"], "independence": "independent"},
                evidence=[
                    {"kind": "specification", "ref": "spec-001"},
                    {"kind": "diff", "ref": "diff-001"},
                    {"kind": "verification", "ref": "tests-001"},
                ],
            )

    adapter = IndependentReviewAdapter(ObservedProvider(), review_context_id="review-session")
    outcome = adapter.review(
        request(),
        package(),
        implementation_context_id="coding-session",
        cycle_number=1,
        runtime_context={
            "core_invocation_id": "core-invocation-001",
            "evidence_binding_root": str(tmp_path / "bindings"),
            "raw_evidence_root": str(raw_root),
            "evidence_policy_ref": "review-lifecycle-policy",
        },
    )
    assert outcome["evidence_binding"]["schema"] == "evidence-binding.v1"
    assert (tmp_path / "bindings" / f"{outcome['evidence_binding']['binding_id']}.json").exists()


def test_configured_core_lifecycle_fails_closed_without_raw_evidence(tmp_path: Path):
    fake = FakeCodeReviewAgent()

    class MissingEvidenceProvider:
        last_observation = {
            "provider": "fake",
            "model": "fake-model",
            "provider_request_id": "provider-request-001",
            "raw_provider_response": None,
        }

        def __call__(self, context):
            return fake.review(
                {"attempt_ref": context["attempt_ref"], "independence": "independent"},
                evidence=[
                    {"kind": "specification", "ref": "spec-001"},
                    {"kind": "diff", "ref": "diff-001"},
                    {"kind": "verification", "ref": "tests-001"},
                ],
            )

    adapter = IndependentReviewAdapter(MissingEvidenceProvider(), review_context_id="review-session")
    with pytest.raises(IndependentReviewError, match="persisted raw provider evidence"):
        adapter.review(
            request(),
            package(),
            implementation_context_id="coding-session",
            cycle_number=1,
            runtime_context={
                "core_invocation_id": "core-invocation-001",
                "evidence_binding_root": str(tmp_path / "bindings"),
                "raw_evidence_root": str(tmp_path / "raw"),
                "evidence_policy_ref": "review-lifecycle-policy",
            },
        )
