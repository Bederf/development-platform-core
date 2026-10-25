"""Executable, provider-neutral bridge for one independent code review.

The bridge owns request validation and cycle coordination, but not provider
credentials, repository access, mutation, or completion authority. A runtime
supplies a bounded :class:`ReviewPackage` and an already isolated reviewer
callable.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .code_review_context import ReviewPackage
from .code_review_provider import CodeReviewProviderAdapter, ProviderCallable
from .evidence_binding import EvidenceBindingError, EvidenceBindingStore, build_binding
from .review_cycle import FakeReviewCycleCoordinator, ReviewCycleError


class IndependentReviewError(ValueError):
    """Raised when an independent-review request cannot be safely executed."""


class IndependentReviewAdapter:
    """Validate, execute, and coordinate one isolated reviewer attempt."""

    REVIEWER_REF = "development-platform-code-reviewer"

    def __init__(
        self,
        provider: ProviderCallable,
        *,
        reviewer_ref: str = REVIEWER_REF,
        review_context_id: str,
    ) -> None:
        if not reviewer_ref.strip():
            raise IndependentReviewError("reviewer_ref is required")
        if not review_context_id.strip():
            raise IndependentReviewError("review_context_id is required")
        self._provider = CodeReviewProviderAdapter(provider)
        self.reviewer_ref = reviewer_ref.strip()
        self.review_context_id = review_context_id.strip()

    @staticmethod
    def make_request(
        *,
        task_ref: str,
        revision_ref: str,
        package_ref: str,
        evidence_refs: list[str],
        reviewer_ref: str = REVIEWER_REF,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Create the versioned request envelope without adding credentials."""

        return {
            "schema": "independent-review-request.v1",
            "request_id": request_id or f"review-request-{uuid4().hex}",
            "task_ref": task_ref,
            "revision_ref": revision_ref,
            "review_package": package_ref,
            "reviewer_ref": reviewer_ref,
            "independence_required": True,
            "evidence_refs": list(evidence_refs),
        }

    def review(
        self,
        request: Mapping[str, Any],
        package: ReviewPackage,
        *,
        implementation_context_id: str,
        cycle_number: int,
        prior_cycle_ref: str | None = None,
        runtime_context: Mapping[str, Any] | None = None,
        max_retries: int = 0,
    ) -> dict[str, Any]:
        """Return a validated review result and its governed cycle record.

        Provider failures are converted into an explicit blocked cycle. They
        never become a passing review and never expose the provider exception
        or any credential-bearing runtime detail.
        """

        self._validate_request(request, package, implementation_context_id)
        if max_retries < 0 or max_retries > 3:
            raise IndependentReviewError("max_retries must be between 0 and 3")
        result: dict[str, Any]
        for retry_number in range(max_retries + 1):
            attempt_context = dict(runtime_context or {})
            if attempt_context:
                attempt_context["retry_count"] = retry_number
                attempt_context["retry_limit"] = max_retries
                if retry_number:
                    attempt_context["provider_request_id"] = f"{attempt_context.get('provider_request_id', 'provider-request')}-retry-{retry_number}-{uuid4().hex}"
            try:
                result = self._provider.review(package, runtime_context=attempt_context or None)
            except Exception as exc:  # provider failures must fail closed
                result = self._blocked_result(package, request, reason=_safe_provider_reason(exc))
            observation = self._provider.last_observation
            if not isinstance(observation, Mapping) or observation.get("failure_classification") != "PROVIDER_UNAVAILABLE":
                break
            if retry_number == max_retries:
                break

        observation = self._provider.last_observation
        if isinstance(observation, Mapping):
            classification = observation.get("failure_classification")
            if classification == "CACHED_REPLAY":
                result = self._blocked_result(package, request, reason="cached_replay")
            elif result.get("disposition") == "CHANGES_REQUIRED":
                observation["failure_classification"] = "IMPLEMENTATION_FINDING"

        validation_error = self._validate_bound_result(result, request, package)
        if validation_error is not None:
            result = self._blocked_result(package, request, reason=validation_error)

        class ResultReviewer:
            def review(self, _package: ReviewPackage) -> Mapping[str, Any]:
                return result

        try:
            cycle = FakeReviewCycleCoordinator(ResultReviewer()).run_cycle(
                package,
                task_ref=str(request["task_ref"]),
                cycle_number=cycle_number,
                prior_cycle_ref=prior_cycle_ref,
            )
        except ReviewCycleError as exc:
            raise IndependentReviewError(f"review cycle could not be created: {exc}") from exc
        outcome = {"review_result": result, "review_cycle": cycle}
        if observation is not None:
            outcome["review_observation"] = dict(observation)
            outcome["gsd_status"] = str(observation.get("status_message") or "Review completed.")
        self._persist_evidence_binding(
            outcome,
            request,
            implementation_context_id=implementation_context_id,
            runtime_context=runtime_context,
            observation=observation,
        )
        return outcome

    def _persist_evidence_binding(
        self,
        outcome: dict[str, Any],
        request: Mapping[str, Any],
        *,
        implementation_context_id: str,
        runtime_context: Mapping[str, Any] | None,
        observation: Mapping[str, Any] | None,
    ) -> None:
        """Persist a binding only when the Core-owned lifecycle is configured.

        Existing provider routing remains unchanged. A configured binding root
        opts the invocation into the evidence lifecycle; incomplete transport
        evidence then fails closed instead of producing an unbound claim.
        """

        if not runtime_context or not runtime_context.get("evidence_binding_root"):
            return
        if not isinstance(observation, Mapping):
            raise IndependentReviewError("evidence binding requires a provider observation")
        raw = observation.get("raw_provider_response")
        raw_ref = observation.get("raw_response_ref")
        policy_ref = runtime_context.get("evidence_policy_ref")
        invocation_id = runtime_context.get("core_invocation_id")
        if not isinstance(raw, str) or not raw or not isinstance(raw_ref, str) or not raw_ref:
            raise IndependentReviewError("evidence binding requires persisted raw provider evidence")
        if not isinstance(policy_ref, str) or not policy_ref.strip() or not isinstance(invocation_id, str) or not invocation_id.strip():
            raise IndependentReviewError("evidence binding requires policy and Core invocation identities")
        try:
            binding = build_binding(
                request,
                outcome["review_result"],
                outcome["review_cycle"],
                raw_evidence=raw,
                raw_evidence_ref=_relative_raw_ref(raw_ref, runtime_context),
                implementation_context_id=implementation_context_id,
                reviewer_context_id=self.review_context_id,
                core_invocation_id=invocation_id,
                provider={
                    "provider_ref": observation.get("provider"),
                    "model": observation.get("model"),
                    "provider_request_id": observation.get("provider_request_id"),
                    "provider_invocation_id": observation.get("omniroute_call_id") or observation.get("generation_id"),
                    "reviewer_ref": self.reviewer_ref,
                },
                policy_ref=policy_ref,
            )
            persisted = EvidenceBindingStore(runtime_context["evidence_binding_root"]).persist(binding)
        except (EvidenceBindingError, OSError, TypeError, KeyError) as exc:
            raise IndependentReviewError(f"evidence binding failed closed: {exc}") from exc
        outcome["evidence_binding"] = persisted


    @staticmethod
    def _has_independent_provider(result: Mapping[str, Any]) -> bool:
        providers = result.get("providers")
        selected = providers.get("selected") if isinstance(providers, Mapping) else None
        if not isinstance(selected, list) or not selected:
            return False
        return not all(
            str(provider).strip().lower() in {"evidence_reviewer", "evidence-reviewer"}
            for provider in selected
        )

    @staticmethod
    def _has_review_evidence(result: Mapping[str, Any]) -> bool:
        evidence = result.get("evidence")
        return isinstance(evidence, list) and len(evidence) >= 3

    @classmethod
    def _validate_bound_result(
        cls,
        result: Mapping[str, Any],
        request: Mapping[str, Any],
        package: ReviewPackage,
    ) -> str | None:
        """Validate provider output before it can enter the review cycle.

        The provider adapter validates the wire shape. This second boundary
        validates binding: the result must belong to this exact revision and
        carry every evidence reference requested for this attempt. A provider
        saying ``PASS`` is never sufficient by itself.
        """

        if result.get("attempt_ref") != package.attempt_ref:
            return "attempt_ref_mismatch"
        if result.get("independence") != "independent":
            return "review_not_independent"
        if not cls._has_independent_provider(result):
            return "evidence_aggregator_is_not_independent"
        if not cls._has_review_evidence(result):
            return "insufficient_review_evidence"
        evidence = result.get("evidence")
        result_refs = {
            str(item.get("ref"))
            for item in evidence
            if isinstance(item, Mapping) and isinstance(item.get("ref"), str)
        }
        requested_refs = {str(ref) for ref in request.get("evidence_refs", [])}
        if not requested_refs.issubset(result_refs):
            return "review_evidence_does_not_match_request"
        return None

    def _validate_request(
        self,
        request: Mapping[str, Any],
        package: ReviewPackage,
        implementation_context_id: str,
    ) -> None:
        if not isinstance(request, Mapping):
            raise IndependentReviewError("request must be an object")
        if not isinstance(implementation_context_id, str) or not implementation_context_id.strip():
            raise IndependentReviewError("implementation_context_id is required")
        if implementation_context_id.strip() == self.review_context_id:
            raise IndependentReviewError("implementation and review contexts must be separate")

        schema = json.loads(
            (Path(__file__).parents[1] / "contracts" / "independent-review-request.v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(dict(request)),
            key=lambda error: list(error.path),
        )
        if errors:
            raise IndependentReviewError(f"invalid independent-review request: {errors[0].message}")
        if request["reviewer_ref"] != self.reviewer_ref:
            raise IndependentReviewError("request reviewer_ref is not registered for this adapter")
        if request["revision_ref"] != package.attempt_ref:
            raise IndependentReviewError("request revision_ref does not match review package")
        if len(request["evidence_refs"]) < 3:
            raise IndependentReviewError("independent review requires specification, diff, and verification evidence")

    def _blocked_result(
        self,
        package: ReviewPackage,
        request: Mapping[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "schema": "code-review-result.v1",
            "review_id": f"review:{request['request_id']}",
            "attempt_ref": package.attempt_ref,
            "independence": "independent",
            "classification": dict(package.classification),
            "providers": {
                "considered": [self.reviewer_ref],
                "selected": [self.reviewer_ref],
                "skipped": [],
            },
            "findings": [{
                "id": "review.provider.failure",
                "severity": "blocker",
                "confidence": "very_high",
                "title": "Independent reviewer did not return a usable result",
                "description": "The review provider failed or returned a result that could not be bound to this attempt.",
                "category": "runtime",
                "evidence_ref": f"request:{request['request_id']}",
                "recommendation": f"Resolve the reviewer failure ({reason}) and rerun in a fresh context.",
                "source": self.reviewer_ref,
            }],
            "disposition": "BLOCKED",
            "evidence": [{"kind": "review-request", "ref": str(ref)} for ref in request["evidence_refs"]],
            "generated_at": datetime.now(UTC).isoformat(),
        }


def _safe_provider_reason(exc: Exception) -> str:
    """Keep bounded contract diagnostics without exposing credential material."""

    detail = " ".join(str(exc).split())[:240]
    detail = re.sub(
        r"(?i)(bearer|api[-_ ]?key|token|secret)\s*[:=]\s*[^,}\s]+",
        r"\1=[redacted]",
        detail,
    )
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _relative_raw_ref(raw_ref: str, runtime_context: Mapping[str, Any]) -> str:
    """Resolve the raw evidence reference relative to the configured source root."""

    root = runtime_context.get("raw_evidence_root")
    if root:
        try:
            return str(Path(raw_ref).resolve().relative_to(Path(str(root)).expanduser().resolve()))
        except ValueError as exc:
            raise EvidenceBindingError("raw evidence reference is outside configured evidence root") from exc
    path = Path(raw_ref)
    if path.is_absolute():
        raise EvidenceBindingError("absolute raw evidence reference requires raw_evidence_root")
    return path.as_posix()
