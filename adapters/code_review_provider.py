"""Provider adapter for the governed code-review result contract.

The provider callable is injected by a development runtime. This module makes
no network or model calls and cannot grant lifecycle authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .code_review_context import ReviewPackage


class CodeReviewProviderError(ValueError):
    """Raised when a provider returns an invalid or unusable result."""


ProviderCallable = Callable[[Mapping[str, Any]], Mapping[str, Any]]

VALID_DISPOSITIONS = frozenset(
    {"PASS", "PASS_WITH_ADVISORIES", "CHANGES_REQUIRED", "INCOMPLETE_REVIEW", "BLOCKED"}
)


def require_exact_disposition(raw: Mapping[str, Any], *, provider: str) -> str:
    """Reject provider-generated enum near-misses instead of repairing them."""

    disposition = raw.get("disposition")
    if not isinstance(disposition, str) or disposition not in VALID_DISPOSITIONS:
        raise CodeReviewProviderError(
            f"{provider} returned an invalid exact disposition; expected one of "
            f"{sorted(VALID_DISPOSITIONS)}"
        )
    return disposition


class CodeReviewProviderAdapter:
    """Call an injected reviewer and validate its result before returning it."""

    def __init__(self, provider: ProviderCallable) -> None:
        self._provider = provider
        self.last_observation: dict[str, Any] | None = None

    def review(
        self,
        package: ReviewPackage,
        *,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider_package = package.as_dict()
        if runtime_context:
            provider_package["_runtime"] = dict(runtime_context)
        try:
            raw = self._provider(provider_package)
        except Exception as exc:
            observation = getattr(self._provider, "last_observation", None)
            if isinstance(observation, Mapping):
                self.last_observation = dict(observation)
            elif runtime_context:
                unavailable = isinstance(exc, (ConnectionError, TimeoutError, OSError)) or "unavailable" in str(exc).lower()
                classification = "PROVIDER_UNAVAILABLE" if unavailable else "INVALID_REVIEW_ARTIFACT"
                self.last_observation = {
                    "provider": str(runtime_context.get("provider") or "unknown"),
                    "model": str(runtime_context.get("model") or "unknown"),
                    "gsd_request_id": str(runtime_context.get("gsd_request_id") or "unknown"),
                    "provider_request_id": str(runtime_context.get("provider_request_id") or "unknown"),
                    "omniroute_call_id": None,
                    "generation_id": None,
                    "fresh_request": True,
                    "cache_status": "UNKNOWN",
                    "response_format": dict(runtime_context.get("response_format") or {}),
                    "schema_version": "code-review-result.v1",
                    "raw_provider_status": "NOT_RECEIVED",
                    "raw_provider_response": None,
                    "failure_classification": classification,
                    "status_message": (
                        "Review blocked by provider availability."
                        if unavailable
                        else "Implementation unchanged. Review artifact invalid."
                    ),
                }
            raise
        if not isinstance(raw, Mapping):
            raise CodeReviewProviderError("review provider must return an object")
        result = dict(raw)
        observation = getattr(self._provider, "last_observation", None)
        if isinstance(observation, Mapping):
            self.last_observation = dict(observation)
        elif runtime_context:
            self.last_observation = {
                "provider": str(runtime_context.get("provider") or "unknown"),
                "model": str(runtime_context.get("model") or "unknown"),
                "gsd_request_id": str(runtime_context.get("gsd_request_id") or "unknown"),
                "provider_request_id": str(runtime_context.get("provider_request_id") or "unknown"),
                "omniroute_call_id": None,
                "generation_id": None,
                "fresh_request": True,
                "cache_status": "NOT_APPLICABLE",
                "response_format": dict(runtime_context.get("response_format") or {}),
                "schema_version": "code-review-result.v1",
                "raw_provider_status": "FAKE_OR_IN_PROCESS",
                "raw_provider_response": None,
                "failure_classification": None,
            }
        schema = json.loads(
            (Path(__file__).parents[1] / "contracts" / "code-review-result.v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(result),
            key=lambda error: list(error.path),
        )
        if errors:
            if self.last_observation is not None:
                self.last_observation["failure_classification"] = "INVALID_REVIEW_ARTIFACT"
                self.last_observation["status_message"] = "Implementation unchanged. Review artifact invalid."
            raise CodeReviewProviderError(f"invalid review result: {errors[0].message}")
        return result
