"""Evidence-backed, directional compatibility evaluation.

Compatibility establishes interoperability facts. It does not select,
authorize, bind, migrate, deploy, or execute either assessed subject.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping, Sequence


Dimension = Literal["structural", "semantic", "behavioral", "operational"]
Direction = Literal["backward", "forward", "mutual"]
EvidenceResult = Literal[
    "backward_compatible",
    "forward_compatible",
    "mutually_compatible",
    "incompatible",
    "unknown",
]
DimensionOutcome = Literal["compatible", "incompatible", "unknown", "expired"]
AssessmentOutcome = Literal["compatible", "incompatible", "unknown", "expired"]
ChangeImpact = Literal["editorial", "additive", "behavioral", "breaking"]

DIMENSIONS: tuple[Dimension, ...] = (
    "structural",
    "semantic",
    "behavioral",
    "operational",
)
RESULTS = frozenset(
    {
        "backward_compatible",
        "forward_compatible",
        "mutually_compatible",
        "incompatible",
        "unknown",
    }
)
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


class CompatibilityInputError(ValueError):
    """Raised when the evaluation request itself is invalid."""


@dataclass(frozen=True)
class CompatibilityEvidence:
    """One independently issued compatibility evidence candidate."""

    evidence_id: str
    version: str
    source: Mapping[str, Any]
    target: Mapping[str, Any]
    dimension: Dimension
    result: EvidenceResult
    change_impact: ChangeImpact
    method: Mapping[str, Any]
    environment: Mapping[str, Any]
    payload: Mapping[str, Any]
    digest: str
    issuer: str
    authority_binding: Mapping[str, Any]
    observed_at: datetime
    validity_scope: Mapping[str, Any]
    effective_from: datetime | None = None
    valid_until: datetime | None = None
    revoked_at: datetime | None = None
    supersedes: str | None = None
    limitations: tuple[str, ...] = ()

    def expected_digest(self) -> str:
        material = {
            "evidence_id": self.evidence_id,
            "version": self.version,
            "source": dict(self.source),
            "target": dict(self.target),
            "dimension": self.dimension,
            "result": self.result,
            "change_impact": self.change_impact,
            "method": dict(self.method),
            "environment": dict(self.environment),
            "payload": dict(self.payload),
            "issuer": self.issuer,
            "authority_binding": dict(self.authority_binding),
            "observed_at": self.observed_at.isoformat(),
            "validity_scope": dict(self.validity_scope),
            "effective_from": (
                self.effective_from.isoformat() if self.effective_from else None
            ),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "supersedes": self.supersedes,
            "limitations": list(self.limitations),
        }
        encoded = json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class CompatibilityFinding:
    dimension: Dimension
    code: str
    evidence_id: str | None
    detail: str


@dataclass(frozen=True)
class CompatibilityDimensionResult:
    dimension: Dimension
    outcome: DimensionOutcome
    directional_result: EvidenceResult | None
    support: Mapping[str, Any] | None
    change_impact: ChangeImpact | None
    method: Mapping[str, Any] | None
    environment: Mapping[str, Any] | None
    valid_until: datetime | None
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class CompatibilityAssessment:
    source: Mapping[str, Any]
    target: Mapping[str, Any]
    requested_direction: Direction
    required_dimensions: tuple[Dimension, ...]
    outcome: AssessmentOutcome
    dimension_results: tuple[CompatibilityDimensionResult, ...]
    findings: tuple[CompatibilityFinding, ...]
    issuer: str
    authority_binding: Mapping[str, Any]
    validity_scope: Mapping[str, Any]
    evaluated_at: datetime


class CompatibilityEvaluator:
    """Evaluate exact versions without inferring compatibility from versions."""

    def __init__(
        self,
        *,
        evaluator_id: str,
        authority_binding: Mapping[str, Any],
        recognized_evidence_issuers: Mapping[str, set[str] | frozenset[str]],
        allowed_clock_skew: timedelta = timedelta(0),
    ) -> None:
        if not evaluator_id:
            raise CompatibilityInputError("evaluator_id is required")
        if not _is_typed_reference(authority_binding, "authority_binding"):
            raise CompatibilityInputError(
                "evaluator authority_binding must be an authority reference"
            )
        if allowed_clock_skew < timedelta(0):
            raise CompatibilityInputError("allowed_clock_skew cannot be negative")
        self.evaluator_id = evaluator_id
        self.authority_binding = dict(authority_binding)
        self.recognized_evidence_issuers = {
            issuer: frozenset(authorities)
            for issuer, authorities in recognized_evidence_issuers.items()
        }
        self.allowed_clock_skew = allowed_clock_skew

    def evaluate(
        self,
        *,
        source: Mapping[str, Any],
        target: Mapping[str, Any],
        requested_direction: Direction,
        required_dimensions: Sequence[Dimension],
        evidence: Sequence[CompatibilityEvidence],
        validity_scope: Mapping[str, Any],
        evaluated_at: datetime,
    ) -> CompatibilityAssessment:
        evaluated_at = _aware_utc(evaluated_at, "evaluated_at")
        if not _is_subject_reference(source) or not _is_subject_reference(target):
            raise CompatibilityInputError(
                "source and target must be exact versioned contract or capability references"
            )
        if requested_direction not in {"backward", "forward", "mutual"}:
            raise CompatibilityInputError("requested_direction is not recognized")
        if (
            not required_dimensions
            or len(set(required_dimensions)) != len(required_dimensions)
            or any(item not in DIMENSIONS for item in required_dimensions)
        ):
            raise CompatibilityInputError(
                "required_dimensions must be unique recognized dimensions"
            )
        if any(item.dimension not in DIMENSIONS for item in evidence):
            raise CompatibilityInputError("evidence dimension is not recognized")
        if not _is_scope(validity_scope):
            raise CompatibilityInputError("validity_scope must be explicit")

        dimensions = tuple(
            dimension for dimension in DIMENSIONS if dimension in required_dimensions
        )
        results: list[CompatibilityDimensionResult] = []
        findings: list[CompatibilityFinding] = []

        for dimension in dimensions:
            candidates = [item for item in evidence if item.dimension == dimension]
            if not candidates:
                results.append(_unknown_result(dimension))
                findings.append(
                    CompatibilityFinding(
                        dimension,
                        "EVIDENCE_MISSING",
                        None,
                        "No compatibility evidence was supplied",
                    )
                )
                continue

            valid_candidates: list[CompatibilityEvidence] = []
            for candidate in candidates:
                invalid = self._evidence_findings(
                    candidate,
                    source=source,
                    target=target,
                    validity_scope=validity_scope,
                    evaluated_at=evaluated_at,
                )
                if invalid:
                    findings.extend(invalid)
                else:
                    valid_candidates.append(candidate)

            if not valid_candidates:
                results.append(_unknown_result(dimension))
                continue

            candidate = _select_current_evidence(valid_candidates)
            if candidate is None:
                results.append(_unknown_result(dimension))
                findings.append(
                    CompatibilityFinding(
                        dimension,
                        "EVIDENCE_AMBIGUOUS",
                        None,
                        "Multiple active compatibility results remain",
                    )
                )
                continue

            support = {
                "semantic_type": "evidence_record",
                "id": candidate.evidence_id,
                "version": candidate.version,
                "digest": candidate.digest,
                "issuer": candidate.issuer,
            }
            if (
                candidate.valid_until is not None
                and evaluated_at - self.allowed_clock_skew
                > _aware_utc(candidate.valid_until, "valid_until")
            ):
                results.append(
                    CompatibilityDimensionResult(
                        dimension,
                        "expired",
                        candidate.result,
                        support,
                        candidate.change_impact,
                        dict(candidate.method),
                        dict(candidate.environment),
                        candidate.valid_until,
                        candidate.limitations,
                    )
                )
                findings.append(
                    CompatibilityFinding(
                        dimension,
                        "EVIDENCE_EXPIRED",
                        candidate.evidence_id,
                        "Compatibility evidence is no longer current",
                    )
                )
                continue

            if candidate.result == "incompatible":
                outcome: DimensionOutcome = "incompatible"
            elif candidate.result == "unknown":
                outcome = "unknown"
            elif _supports_direction(candidate.result, requested_direction):
                outcome = "compatible"
            else:
                outcome = "unknown"
                findings.append(
                    CompatibilityFinding(
                        dimension,
                        "DIRECTION_NOT_ESTABLISHED",
                        candidate.evidence_id,
                        "Evidence establishes a different compatibility direction",
                    )
                )
            results.append(
                CompatibilityDimensionResult(
                    dimension,
                    outcome,
                    candidate.result,
                    support,
                    candidate.change_impact,
                    dict(candidate.method),
                    dict(candidate.environment),
                    candidate.valid_until,
                    candidate.limitations,
                )
            )

        return CompatibilityAssessment(
            source=dict(source),
            target=dict(target),
            requested_direction=requested_direction,
            required_dimensions=dimensions,
            outcome=_summary_outcome(item.outcome for item in results),
            dimension_results=tuple(results),
            findings=tuple(findings),
            issuer=self.evaluator_id,
            authority_binding=dict(self.authority_binding),
            validity_scope=dict(validity_scope),
            evaluated_at=evaluated_at,
        )

    def _evidence_findings(
        self,
        evidence: CompatibilityEvidence,
        *,
        source: Mapping[str, Any],
        target: Mapping[str, Any],
        validity_scope: Mapping[str, Any],
        evaluated_at: datetime,
    ) -> list[CompatibilityFinding]:
        findings: list[CompatibilityFinding] = []

        def add(code: str, detail: str) -> None:
            findings.append(
                CompatibilityFinding(
                    evidence.dimension, code, evidence.evidence_id, detail
                )
            )

        if (
            not evidence.evidence_id
            or not IDENTIFIER_PATTERN.fullmatch(evidence.evidence_id)
            or not evidence.version
        ):
            add("EVIDENCE_IDENTITY_INVALID", "Evidence identity is invalid")
        if evidence.result not in RESULTS:
            add("EVIDENCE_RESULT_INVALID", "Compatibility result is not recognized")
        if evidence.change_impact not in {
            "editorial",
            "additive",
            "behavioral",
            "breaking",
        }:
            add("CHANGE_IMPACT_INVALID", "Change impact is not recognized")
        if not _same_reference(evidence.source, source):
            add("SOURCE_MISMATCH", "Evidence source version does not match")
        if not _same_reference(evidence.target, target):
            add("TARGET_MISMATCH", "Evidence target version does not match")
        if not _is_typed_reference(evidence.method, "evaluation_definition"):
            add("METHOD_INVALID", "Method must be an evaluation reference")
        if not _is_typed_reference(evidence.environment, "environment"):
            add("ENVIRONMENT_INVALID", "Environment must be a versioned reference")
        if not _is_typed_reference(evidence.authority_binding, "authority_binding"):
            add("EVIDENCE_AUTHORITY_INVALID", "Authority reference is invalid")
        if evidence.validity_scope != validity_scope:
            add("SCOPE_MISMATCH", "Evidence scope does not match evaluation scope")
        source_issuer = source.get("issuer")
        target_issuer = target.get("issuer")
        if evidence.issuer in {source_issuer, target_issuer}:
            add("SELF_CERTIFICATION_PROHIBITED", "A subject issuer cannot self-certify")
        recognized = self.recognized_evidence_issuers.get(evidence.issuer)
        authority_id = evidence.authority_binding.get("id")
        if recognized is None:
            add("EVIDENCE_ISSUER_UNRECOGNIZED", "Evidence issuer is not recognized")
        elif authority_id not in recognized:
            add("EVIDENCE_AUTHORITY_UNRECOGNIZED", "Authority is not recognized")
        if evidence.digest != evidence.expected_digest():
            add("DIGEST_MISMATCH", "Evidence envelope digest does not match")

        observed_at = _safe_time(evidence.observed_at, "observed_at", add)
        effective_from = _optional_time(evidence.effective_from, "effective_from", add)
        valid_until = _optional_time(evidence.valid_until, "valid_until", add)
        revoked_at = _optional_time(evidence.revoked_at, "revoked_at", add)
        if (
            observed_at is not None
            and observed_at > evaluated_at + self.allowed_clock_skew
        ):
            add("EVIDENCE_FROM_FUTURE", "Evidence was observed after evaluation")
        if (
            effective_from is not None
            and effective_from > evaluated_at + self.allowed_clock_skew
        ):
            add("EVIDENCE_NOT_EFFECTIVE", "Evidence validity has not started")
        if revoked_at is not None and revoked_at <= evaluated_at:
            add("EVIDENCE_REVOKED", "Evidence was revoked before evaluation")
        if (
            observed_at is not None
            and valid_until is not None
            and observed_at > valid_until
        ):
            add("VALIDITY_WINDOW_INVALID", "Evidence expired before observation")
        if (
            effective_from is not None
            and valid_until is not None
            and effective_from > valid_until
        ):
            add("VALIDITY_WINDOW_INVALID", "Evidence expires before effectivity")
        if (
            observed_at is not None
            and revoked_at is not None
            and revoked_at < observed_at
        ):
            add("REVOCATION_TIME_INVALID", "Evidence was revoked before observation")
        return findings


def _supports_direction(result: EvidenceResult, direction: Direction) -> bool:
    return result == "mutually_compatible" or result == f"{direction}_compatible"


def _summary_outcome(outcomes: Iterable[DimensionOutcome]) -> AssessmentOutcome:
    values = tuple(outcomes)
    if any(value == "incompatible" for value in values):
        return "incompatible"
    if any(value == "expired" for value in values):
        return "expired"
    if any(value == "unknown" for value in values) or not values:
        return "unknown"
    return "compatible"


def _unknown_result(dimension: Dimension) -> CompatibilityDimensionResult:
    return CompatibilityDimensionResult(
        dimension, "unknown", None, None, None, None, None, None, ()
    )


def _is_reference(value: Mapping[str, Any]) -> bool:
    allowed = {"semantic_type", "id", "version", "digest", "issuer"}
    return (
        set(value).issubset(allowed)
        and all(
            isinstance(value.get(field), str) and value[field]
            for field in ("semantic_type", "id", "version")
        )
        and all(
            value.get(field) is None or isinstance(value[field], str)
            for field in ("digest", "issuer")
        )
    )


def _is_typed_reference(value: Mapping[str, Any], semantic_type: str) -> bool:
    return _is_reference(value) and value.get("semantic_type") == semantic_type


def _is_subject_reference(value: Mapping[str, Any]) -> bool:
    return _is_reference(value) and value.get("semantic_type") in {
        "contract",
        "capability_definition",
        "capability_profile",
    }


def _same_reference(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    fields = ["semantic_type", "id", "version"]
    if right.get("digest") is not None:
        fields.append("digest")
    return all(left.get(field) == right.get(field) for field in fields)


def _is_scope(value: Mapping[str, Any]) -> bool:
    return set(value) == {"scope_type", "scope_id"} and all(
        isinstance(value.get(field), str) and value[field]
        for field in ("scope_type", "scope_id")
    )


def _aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CompatibilityInputError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _safe_time(value: datetime, field: str, add: Any) -> datetime | None:
    try:
        return _aware_utc(value, field)
    except CompatibilityInputError as exc:
        add("EVIDENCE_TIME_INVALID", str(exc))
        return None


def _optional_time(value: datetime | None, field: str, add: Any) -> datetime | None:
    return None if value is None else _safe_time(value, field, add)


def _select_current_evidence(
    candidates: Sequence[CompatibilityEvidence],
) -> CompatibilityEvidence | None:
    if len(candidates) == 1:
        return candidates[0]
    by_id = {candidate.evidence_id: candidate for candidate in candidates}
    if len(by_id) != len(candidates):
        return None
    superseded: set[str] = set()
    for candidate in candidates:
        if candidate.supersedes is None:
            continue
        prior = by_id.get(candidate.supersedes)
        if prior is None or prior.issuer != candidate.issuer:
            return None
        superseded.add(prior.evidence_id)
    heads = [
        candidate for candidate in candidates if candidate.evidence_id not in superseded
    ]
    return heads[0] if len(heads) == 1 else None
