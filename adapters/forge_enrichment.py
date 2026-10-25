"""Provider-neutral semantic enrichment for the Forge contract adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


class EnrichmentError(ValueError):
    """Raised when semantic enrichment is incomplete or inconsistent."""


@dataclass(frozen=True)
class ForgeSemanticEnrichment:
    evaluator_actor: dict[str, Any]
    evaluator_binding: dict[str, Any]
    evaluation_profile: dict[str, Any]
    evaluation_method: dict[str, Any]
    subject: dict[str, Any]
    authority_binding: dict[str, Any]
    request: dict[str, Any]
    correlation: dict[str, Any]
    provenance: dict[str, Any]
    availability: dict[str, Any]
    failure: dict[str, Any] | None = None


class ForgeEnrichmentProvider(Protocol):
    def enrich(self, *, verification_attempt_id: str, provider_output: dict[str, Any]) -> ForgeSemanticEnrichment: ...


class StaticForgeEnrichmentProvider:
    """Small deterministic provider used for adapter qualification."""

    def __init__(self, enrichment: ForgeSemanticEnrichment) -> None:
        self.enrichment = enrichment

    def enrich(self, *, verification_attempt_id: str, provider_output: dict[str, Any]) -> ForgeSemanticEnrichment:
        if not verification_attempt_id:
            raise EnrichmentError("verification attempt identity is required")
        if provider_output.get("verification_attempt_id") != verification_attempt_id:
            raise EnrichmentError("provider output correlation mismatch")
        e = self.enrichment
        required = (e.evaluator_actor, e.evaluator_binding, e.evaluation_profile, e.evaluation_method,
                    e.subject, e.authority_binding, e.request, e.correlation, e.provenance, e.availability)
        if any(not isinstance(value, dict) or not value for value in required):
            raise EnrichmentError("semantic enrichment is incomplete")
        if e.correlation.get("verification_attempt_id") != verification_attempt_id:
            raise EnrichmentError("enrichment correlation mismatch")
        state = e.availability.get("state")
        if state not in {"assessed", "unavailable", "not_assessed", "not_applicable"}:
            raise EnrichmentError("invalid availability state")
        if state != "assessed" and e.failure is None:
            raise EnrichmentError("unavailable enrichment requires explicit failure semantics")
        return e
