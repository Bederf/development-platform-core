"""Structural validation and evidence-backed capability conformance.

This module consumes ``capability-definition.v1``. It establishes bounded
facts about conformance and deliberately does not resolve requirements, select
implementations, authorize bindings, or execute engineering work.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from jsonschema import Draft202012Validator


Dimension = Literal["structural", "semantic", "behavioral", "operational"]
EvidenceOutcome = Literal["satisfied", "failed", "unknown"]
ClaimOutcome = Literal["satisfied", "failed", "unknown", "expired"]
AssessmentOutcome = Literal["satisfied", "failed", "unknown", "expired"]

DIMENSIONS: tuple[Dimension, ...] = (
    "structural",
    "semantic",
    "behavioral",
    "operational",
)
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


class ConformanceInputError(ValueError):
    """Raised when the evaluator itself is configured with invalid input."""


@dataclass(frozen=True)
class DocumentValidation:
    """A deterministic structural-validation result."""

    valid: bool
    errors: tuple[str, ...]


class CapabilityContractValidator:
    """Validate individual documents against the promoted contract family."""

    def __init__(self, schema_path: str | Path | None = None) -> None:
        if schema_path is None:
            schema_path = (
                Path(__file__).parents[1]
                / "contracts"
                / "capability-definition.v1.schema.json"
            )
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def validate(self, document: Mapping[str, Any]) -> DocumentValidation:
        errors = tuple(
            sorted(
                self._format_error(error)
                for error in self._validator.iter_errors(dict(document))
            )
        )
        return DocumentValidation(valid=not errors, errors=errors)

    @staticmethod
    def _format_error(error: Any) -> str:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        return f"{path}: {error.message}"


@dataclass(frozen=True)
class ConformanceEvidence:
    """An admitted evidence candidate used to support one conformance claim.

    This is an implementation input, not a new public contract family. The
    evidence is preserved by reference in the resulting ConformanceClaim.
    """

    evidence_id: str
    version: str
    subject: Mapping[str, Any]
    capability: Mapping[str, Any]
    contracts: tuple[Mapping[str, Any], ...]
    dimension: Dimension
    outcome: EvidenceOutcome
    method: Mapping[str, Any]
    environment: Mapping[str, Any]
    payload: Mapping[str, Any]
    digest: str
    issuer: str
    authority_binding: Mapping[str, Any]
    observed_at: datetime
    valid_until: datetime | None
    validity_scope: Mapping[str, Any]
    effective_from: datetime | None = None
    revoked_at: datetime | None = None
    supersedes: str | None = None
    limitations: tuple[str, ...] = ()

    def expected_digest(self) -> str:
        """Digest the complete semantic evidence envelope, excluding digest."""

        material = {
            "evidence_id": self.evidence_id,
            "version": self.version,
            "subject": dict(self.subject),
            "capability": dict(self.capability),
            "contracts": [dict(reference) for reference in self.contracts],
            "dimension": self.dimension,
            "outcome": self.outcome,
            "method": dict(self.method),
            "environment": dict(self.environment),
            "payload": dict(self.payload),
            "issuer": self.issuer,
            "authority_binding": dict(self.authority_binding),
            "observed_at": self.observed_at.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "validity_scope": dict(self.validity_scope),
            "effective_from": (
                self.effective_from.isoformat() if self.effective_from else None
            ),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "supersedes": self.supersedes,
            "limitations": list(self.limitations),
        }
        encoded = json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class ConformanceFinding:
    """One attributable reason a dimension could or could not be claimed."""

    dimension: Dimension
    code: str
    evidence_id: str | None
    detail: str


@dataclass(frozen=True)
class ConformanceAssessment:
    """Bounded evaluator output; it is factual and carries no permission."""

    subject: Mapping[str, Any]
    capability: Mapping[str, Any]
    required_dimensions: tuple[Dimension, ...]
    outcome: AssessmentOutcome
    claims: tuple[Mapping[str, Any], ...]
    findings: tuple[ConformanceFinding, ...]
    evaluated_at: datetime


class ConformanceEvaluator:
    """Produce schema-valid claims only from valid independent evidence."""

    def __init__(
        self,
        *,
        evaluator_id: str,
        authority_binding: Mapping[str, Any],
        recognized_evidence_issuers: Mapping[str, set[str] | frozenset[str]],
        allowed_clock_skew: timedelta = timedelta(0),
        validator: CapabilityContractValidator | None = None,
    ) -> None:
        if not evaluator_id:
            raise ConformanceInputError("evaluator_id is required")
        if (
            not _is_reference(authority_binding)
            or authority_binding.get("semantic_type") != "authority_binding"
        ):
            raise ConformanceInputError(
                "evaluator authority_binding must be a reference"
            )
        if allowed_clock_skew < timedelta(0):
            raise ConformanceInputError("allowed_clock_skew cannot be negative")
        self.evaluator_id = evaluator_id
        self.authority_binding = dict(authority_binding)
        self.recognized_evidence_issuers = {
            issuer: frozenset(authorities)
            for issuer, authorities in recognized_evidence_issuers.items()
        }
        self.allowed_clock_skew = allowed_clock_skew
        self.validator = validator or CapabilityContractValidator()

    def evaluate(
        self,
        *,
        capability: Mapping[str, Any],
        implementation: Mapping[str, Any],
        evidence: Sequence[ConformanceEvidence],
        evaluated_at: datetime,
    ) -> ConformanceAssessment:
        evaluated_at = _aware_utc(evaluated_at, "evaluated_at")
        if any(item.dimension not in DIMENSIONS for item in evidence):
            raise ConformanceInputError("evidence dimension is not recognized")
        required_dimensions = self._validate_subjects(capability, implementation)
        subject_ref = _implementation_reference(implementation)
        capability_ref = _capability_reference(capability)

        claims: list[Mapping[str, Any]] = []
        findings: list[ConformanceFinding] = []
        dimension_outcomes: dict[Dimension, ClaimOutcome] = {}

        for dimension in required_dimensions:
            candidates = [item for item in evidence if item.dimension == dimension]
            if not candidates:
                dimension_outcomes[dimension] = "unknown"
                findings.append(
                    ConformanceFinding(
                        dimension,
                        "EVIDENCE_MISSING",
                        None,
                        "No evidence was supplied for the required dimension",
                    )
                )
                continue

            valid_candidates: list[ConformanceEvidence] = []
            for candidate in candidates:
                invalid = self._evidence_findings(
                    candidate,
                    capability_ref=capability_ref,
                    subject_ref=subject_ref,
                    implementation_issuer=implementation["issuer"],
                    evaluated_at=evaluated_at,
                )
                if invalid:
                    findings.extend(invalid)
                else:
                    valid_candidates.append(candidate)

            if not valid_candidates:
                dimension_outcomes[dimension] = "unknown"
                continue

            candidate = _select_current_evidence(valid_candidates)
            if candidate is None:
                dimension_outcomes[dimension] = "unknown"
                findings.append(
                    ConformanceFinding(
                        dimension,
                        "EVIDENCE_AMBIGUOUS",
                        None,
                        "Multiple unsuperseded evidence candidates were supplied",
                    )
                )
                continue

            outcome: ClaimOutcome = candidate.outcome
            if (
                candidate.valid_until is not None
                and evaluated_at - self.allowed_clock_skew
                > _aware_utc(candidate.valid_until, "valid_until")
            ):
                outcome = "expired"
                findings.append(
                    ConformanceFinding(
                        dimension,
                        "EVIDENCE_EXPIRED",
                        candidate.evidence_id,
                        "The evidence validity window ended before evaluation",
                    )
                )

            claim = self._claim(
                candidate,
                capability_ref=capability_ref,
                subject_ref=subject_ref,
                outcome=outcome,
                evaluated_at=evaluated_at,
            )
            validation = self.validator.validate(claim)
            if not validation.valid:
                raise ConformanceInputError(
                    "evaluator produced an invalid ConformanceClaim: "
                    + "; ".join(validation.errors)
                )
            claims.append(claim)
            dimension_outcomes[dimension] = outcome

        return ConformanceAssessment(
            subject=subject_ref,
            capability=capability_ref,
            required_dimensions=required_dimensions,
            outcome=_summary_outcome(dimension_outcomes.values()),
            claims=tuple(claims),
            findings=tuple(findings),
            evaluated_at=evaluated_at,
        )

    def _validate_subjects(
        self,
        capability: Mapping[str, Any],
        implementation: Mapping[str, Any],
    ) -> tuple[Dimension, ...]:
        capability_validation = self.validator.validate(capability)
        implementation_validation = self.validator.validate(implementation)
        if not capability_validation.valid:
            raise ConformanceInputError(
                "capability is structurally invalid: "
                + "; ".join(capability_validation.errors)
            )
        if capability["entity_type"] not in {
            "capability_definition",
            "capability_profile",
        }:
            raise ConformanceInputError("capability must be a definition or profile")
        if not implementation_validation.valid:
            raise ConformanceInputError(
                "implementation is structurally invalid: "
                + "; ".join(implementation_validation.errors)
            )
        if implementation["entity_type"] != "implementation_descriptor":
            raise ConformanceInputError("implementation must be a descriptor")

        capability_ref = _capability_reference(capability)
        if not any(
            _same_reference(reference, capability_ref)
            for reference in implementation["declared_capabilities"]
        ):
            raise ConformanceInputError(
                "implementation does not declare the assessed capability"
            )

        required = capability["conformance_requirements"]
        return tuple(dimension for dimension in DIMENSIONS if dimension in required)

    def _evidence_findings(
        self,
        evidence: ConformanceEvidence,
        *,
        capability_ref: Mapping[str, Any],
        subject_ref: Mapping[str, Any],
        implementation_issuer: str,
        evaluated_at: datetime,
    ) -> list[ConformanceFinding]:
        findings: list[ConformanceFinding] = []

        def add(code: str, detail: str) -> None:
            findings.append(
                ConformanceFinding(
                    evidence.dimension, code, evidence.evidence_id, detail
                )
            )

        if (
            not evidence.evidence_id
            or not IDENTIFIER_PATTERN.fullmatch(evidence.evidence_id)
            or not evidence.version
        ):
            add(
                "EVIDENCE_IDENTITY_INVALID",
                "Evidence identity and version are required",
            )
        if evidence.outcome not in {"satisfied", "failed", "unknown"}:
            add("EVIDENCE_OUTCOME_INVALID", "Evidence outcome is not recognized")
        if not evidence.contracts:
            add("CONTRACT_SUPPORT_MISSING", "Evidence must identify assessed contracts")
        elif not all(
            _is_reference(reference) and reference.get("semantic_type") == "contract"
            for reference in evidence.contracts
        ):
            add(
                "CONTRACT_SUPPORT_INVALID",
                "Every assessed contract must be a versioned reference",
            )
        if not _same_reference(evidence.subject, subject_ref, include_digest=True):
            add(
                "SUBJECT_MISMATCH",
                "Evidence does not assess the requested implementation",
            )
        if not _same_reference(evidence.capability, capability_ref):
            add(
                "CAPABILITY_MISMATCH",
                "Evidence does not assess the requested capability",
            )
        if (
            not _is_reference(evidence.method)
            or evidence.method.get("semantic_type") != "evaluation_definition"
        ):
            add("METHOD_INVALID", "Evaluation method must be a versioned reference")
        if (
            not _is_reference(evidence.environment)
            or evidence.environment.get("semantic_type") != "environment"
        ):
            add("ENVIRONMENT_INVALID", "Environment must be a versioned reference")
        if not _is_scope(evidence.validity_scope):
            add("VALIDITY_SCOPE_INVALID", "Evidence validity scope must be explicit")
        if (
            not _is_reference(evidence.authority_binding)
            or evidence.authority_binding.get("semantic_type") != "authority_binding"
        ):
            add(
                "EVIDENCE_AUTHORITY_INVALID",
                "Evidence authority must be a versioned reference",
            )
        if evidence.issuer == implementation_issuer:
            add(
                "SELF_CERTIFICATION_PROHIBITED",
                "Implementation issuer cannot evaluate itself",
            )
        authority_id = evidence.authority_binding.get("id")
        recognized = self.recognized_evidence_issuers.get(evidence.issuer)
        if recognized is None:
            add("EVIDENCE_ISSUER_UNRECOGNIZED", "Evidence issuer is not recognized")
        elif authority_id not in recognized:
            add(
                "EVIDENCE_AUTHORITY_UNRECOGNIZED",
                "Evidence authority is not recognized",
            )
        if evidence.digest != evidence.expected_digest():
            add("DIGEST_MISMATCH", "Evidence envelope digest does not match")
        observed_at: datetime | None = None
        try:
            observed_at = _aware_utc(evidence.observed_at, "observed_at")
            if observed_at > evaluated_at + self.allowed_clock_skew:
                add(
                    "EVIDENCE_FROM_FUTURE",
                    "Evidence was observed after evaluation time",
                )
        except ConformanceInputError as exc:
            add("EVIDENCE_TIME_INVALID", str(exc))
        effective_from: datetime | None = None
        if evidence.effective_from is not None:
            try:
                effective_from = _aware_utc(evidence.effective_from, "effective_from")
                if effective_from > evaluated_at + self.allowed_clock_skew:
                    add(
                        "EVIDENCE_NOT_EFFECTIVE",
                        "Evidence validity has not started",
                    )
            except ConformanceInputError as exc:
                add("EVIDENCE_TIME_INVALID", str(exc))
        revoked_at: datetime | None = None
        if evidence.revoked_at is not None:
            try:
                revoked_at = _aware_utc(evidence.revoked_at, "revoked_at")
                if revoked_at <= evaluated_at:
                    add("EVIDENCE_REVOKED", "Evidence was revoked before evaluation")
            except ConformanceInputError as exc:
                add("EVIDENCE_TIME_INVALID", str(exc))
        if evidence.valid_until is not None:
            try:
                valid_until = _aware_utc(evidence.valid_until, "valid_until")
                if observed_at is not None and observed_at > valid_until:
                    add(
                        "VALIDITY_WINDOW_INVALID",
                        "Evidence cannot expire before it was observed",
                    )
                if effective_from is not None and effective_from > valid_until:
                    add(
                        "VALIDITY_WINDOW_INVALID",
                        "Evidence cannot expire before becoming effective",
                    )
            except ConformanceInputError as exc:
                add("EVIDENCE_TIME_INVALID", str(exc))
        if (
            revoked_at is not None
            and observed_at is not None
            and revoked_at < observed_at
        ):
            add(
                "REVOCATION_TIME_INVALID",
                "Evidence cannot be revoked before it was observed",
            )
        return findings

    def _claim(
        self,
        evidence: ConformanceEvidence,
        *,
        capability_ref: Mapping[str, Any],
        subject_ref: Mapping[str, Any],
        outcome: ClaimOutcome,
        evaluated_at: datetime,
    ) -> Mapping[str, Any]:
        return {
            "schema": "capability-definition.v1",
            "entity_type": "conformance_claim",
            "claim_id": _claim_id(
                subject_ref["id"], evidence.dimension, evidence.evidence_id
            ),
            "subject": dict(subject_ref),
            "capability": dict(capability_ref),
            "contracts": [dict(reference) for reference in evidence.contracts],
            "dimension": evidence.dimension,
            "outcome": outcome,
            "method": dict(evidence.method),
            "environment": dict(evidence.environment),
            "supports": [
                {
                    "semantic_type": "evidence_record",
                    "id": evidence.evidence_id,
                    "version": evidence.version,
                    "digest": evidence.digest,
                    "issuer": evidence.issuer,
                }
            ],
            "issuer": self.evaluator_id,
            "authority_binding": dict(self.authority_binding),
            "assessment_time": evaluated_at.isoformat().replace("+00:00", "Z"),
            "validity": {
                "scope": dict(evidence.validity_scope),
                "valid_until": (
                    evidence.valid_until.isoformat().replace("+00:00", "Z")
                    if evidence.valid_until
                    else None
                ),
            },
            "limitations": list(evidence.limitations),
            "supersession": (
                {
                    "semantic_type": "conformance_claim",
                    "id": _claim_id(
                        subject_ref["id"], evidence.dimension, evidence.supersedes
                    ),
                    "version": evidence.version,
                }
                if evidence.supersedes
                else None
            ),
        }


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


def _is_scope(value: Mapping[str, Any]) -> bool:
    return set(value) == {"scope_type", "scope_id"} and all(
        isinstance(value.get(field), str) and value[field]
        for field in ("scope_type", "scope_id")
    )


def _same_reference(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    include_digest: bool = False,
) -> bool:
    fields = ["semantic_type", "id", "version"]
    if include_digest and right.get("digest") is not None:
        fields.append("digest")
    return all(left.get(field) == right.get(field) for field in fields)


def _capability_reference(capability: Mapping[str, Any]) -> Mapping[str, Any]:
    id_field = (
        "capability_id"
        if capability["entity_type"] == "capability_definition"
        else "profile_id"
    )
    return {
        "semantic_type": capability["entity_type"],
        "id": capability[id_field],
        "version": capability["version"],
    }


def _implementation_reference(implementation: Mapping[str, Any]) -> Mapping[str, Any]:
    reference: dict[str, Any] = {
        "semantic_type": "implementation_descriptor",
        "id": implementation["implementation_id"],
        "version": implementation["version"],
    }
    if implementation.get("digest") is not None:
        reference["digest"] = implementation["digest"]
    return reference


def _claim_id(subject_id: str, dimension: Dimension, evidence_id: str) -> str:
    return f"claim.{subject_id}.{dimension}.{evidence_id}"


def _select_current_evidence(
    candidates: Sequence[ConformanceEvidence],
) -> ConformanceEvidence | None:
    """Select one explicit supersession head; never rank competing evidence."""

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


def _aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ConformanceInputError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _summary_outcome(outcomes: Iterable[ClaimOutcome]) -> AssessmentOutcome:
    values = tuple(outcomes)
    if any(value == "failed" for value in values):
        return "failed"
    if any(value == "expired" for value in values):
        return "expired"
    if any(value == "unknown" for value in values) or not values:
        return "unknown"
    return "satisfied"
