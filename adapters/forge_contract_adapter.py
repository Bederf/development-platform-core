"""Fail-closed mapping boundary from Forge observations to Core candidates.

This adapter deliberately does not interpret lifecycle PASS as semantic success.
It requires an enriched, attributable observation before emitting an evaluation
or evidence candidate. Policy, admission, acceptance, and Gateway authority
remain outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .forge_enrichment import ForgeEnrichmentProvider


class ForgeMappingError(ValueError):
    """Raised when Forge output cannot be mapped safely to Core semantics."""


@dataclass(frozen=True)
class ForgeObservation:
    verification_attempt_id: str
    status: Literal["PASS", "FAIL", "INCOMPLETE", "NOT_RUN"]
    checks: tuple[dict[str, Any], ...]
    raw_log: str | None = None
    artifacts: tuple[dict[str, Any], ...] = ()


class ForgeContractAdapter:
    """Convert enriched Forge observations into non-authoritative candidates."""

    REQUIRED_EVALUATION = frozenset(
        {"request", "definition", "profile", "subject", "evaluator_actor", "evaluator_binding", "method", "authority_binding"}
    )

    def evaluation_from_provider(self, observation: ForgeObservation, provider: ForgeEnrichmentProvider, provider_output: dict[str, Any]) -> dict[str, Any]:
        """Enrich a real provider observation, then apply the same fail-closed gate."""
        enriched = provider.enrich(
            verification_attempt_id=observation.verification_attempt_id,
            provider_output=provider_output,
        )
        values = {
            "request": enriched.request,
            "definition": enriched.evaluation_method,
            "profile": enriched.evaluation_profile,
            "subject": enriched.subject,
            "evaluator_actor": enriched.evaluator_actor,
            "evaluator_binding": enriched.evaluator_binding,
            "method": enriched.evaluation_method,
            "authority_binding": enriched.authority_binding,
            "correlation": enriched.correlation,
            "provenance": enriched.provenance,
            "availability": enriched.availability,
            "failure": enriched.failure,
        }
        return self.evaluation_candidate(observation, values)

    def evaluation_candidate(self, observation: ForgeObservation, enrichment: dict[str, Any]) -> dict[str, Any]:
        missing = sorted(self.REQUIRED_EVALUATION - enrichment.keys())
        if missing:
            raise ForgeMappingError(f"insufficient semantic material: {', '.join(missing)}")
        if not observation.verification_attempt_id:
            raise ForgeMappingError("verification attempt identity is required")
        if observation.status == "PASS" and not observation.checks:
            raise ForgeMappingError("PASS without check observations cannot become satisfied")
        return {
            "candidate_type": "evaluation_result",
            "authoritative": False,
            "verification_attempt_id": observation.verification_attempt_id,
            "provider_status": observation.status,
            "checks": list(observation.checks),
            **enrichment,
        }

    def evidence_candidate(self, observation: ForgeObservation, evaluation: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
        if evaluation.get("candidate_type") != "evaluation_result" or evaluation.get("authoritative") is not False:
            raise ForgeMappingError("evidence requires a non-authoritative evaluation candidate")
        required = {"subject", "producer", "submitted_by", "collection_method"}
        missing = sorted(required - provenance.keys())
        if missing:
            raise ForgeMappingError(f"insufficient evidence provenance: {', '.join(missing)}")
        return {
            "candidate_type": "evidence_submission",
            "authoritative": False,
            "verification_attempt_id": observation.verification_attempt_id,
            "evaluation": evaluation,
            "provenance": provenance,
            "raw_log": observation.raw_log,
            "artifacts": list(observation.artifacts),
        }

    def change_surface_candidate(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Map a change-surface signal without granting Core acceptance."""
        if signal.get("schema") != "change-surface-verification.v1":
            raise ForgeMappingError("unsupported change-surface signal schema")
        if signal.get("signal") not in {"PASS", "REVIEW_REQUIRED", "INCOMPLETE"}:
            raise ForgeMappingError("invalid change-surface signal")
        if signal.get("authoritative") is not False:
            raise ForgeMappingError("change-surface signal must remain non-authoritative")
        if not isinstance(signal.get("identity"), dict) or not signal["identity"].get("attempt_id"):
            raise ForgeMappingError("change-surface signal requires attempt identity")
        return {
            "candidate_type": "change_surface_result",
            "authoritative": False,
            **signal,
        }
