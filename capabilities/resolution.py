"""Deterministic requirement reconciliation and candidate admission.

Resolution derives governed facts. It does not select an implementation,
evaluate policy, create a binding, provision resources, or execute work.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

from .conformance import CapabilityContractValidator


FactOutcome = Literal["satisfied", "failed", "unknown", "expired"]
CompatibilityOutcome = Literal["compatible", "incompatible", "unknown", "expired"]


class ResolutionInputError(ValueError):
    """Raised when the resolver is configured with invalid governed input."""


@dataclass(frozen=True)
class ResolutionFinding:
    code: str
    subject_id: str
    detail: str


@dataclass(frozen=True)
class RequirementResolution:
    effective_requirements: tuple[Mapping[str, Any], ...]
    rejected_requirements: tuple[Mapping[str, Any], ...]
    findings: tuple[ResolutionFinding, ...]
    unresolved: tuple[Mapping[str, Any], ...]
    record: Mapping[str, Any]


@dataclass(frozen=True)
class AssessedFact:
    """A reference to an independently assessed compatibility or constraint fact."""

    reference: Mapping[str, Any]
    outcome: FactOutcome | CompatibilityOutcome
    issuer: str
    authority_binding: Mapping[str, Any]
    validity_scope: Mapping[str, Any]
    valid_until: datetime | None = None
    digest: str = ""

    def expected_digest(self) -> str:
        material = {
            "reference": dict(self.reference),
            "outcome": self.outcome,
            "issuer": self.issuer,
            "authority_binding": dict(self.authority_binding),
            "validity_scope": dict(self.validity_scope),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class CandidateFacts:
    implementation: Mapping[str, Any]
    conformance_claims: tuple[Mapping[str, Any], ...]
    compatibility: tuple[AssessedFact, ...] = ()
    constraints: tuple[AssessedFact, ...] = ()
    risk_assessments: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class PolicyInputPackage:
    requirement: Mapping[str, Any]
    resolution: Mapping[str, Any]
    eligible_candidates: tuple[Mapping[str, Any], ...]
    rejected_candidates: tuple[Mapping[str, Any], ...]
    conformance_claims: tuple[Mapping[str, Any], ...]
    compatibility_assessments: tuple[Mapping[str, Any], ...]
    constraint_assessments: tuple[Mapping[str, Any], ...]
    risk_assessments: tuple[Mapping[str, Any], ...]
    unresolved: tuple[Mapping[str, Any], ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class CandidateResolution:
    eligible_candidates: tuple[Mapping[str, Any], ...]
    rejected_candidates: tuple[Mapping[str, Any], ...]
    findings: tuple[ResolutionFinding, ...]
    policy_input: PolicyInputPackage


class RequirementResolver:
    """Reconcile authoritative capability requirements without selecting."""

    METHOD = {
        "semantic_type": "resolution_method",
        "id": "core.requirement-resolution",
        "version": "1.0.0",
    }

    def __init__(
        self,
        *,
        resolver_id: str,
        recognized_requirement_issuers: Mapping[str, set[str] | frozenset[str]],
        validator: CapabilityContractValidator | None = None,
    ) -> None:
        if not resolver_id:
            raise ResolutionInputError("resolver_id is required")
        self.resolver_id = resolver_id
        self.recognized_requirement_issuers = {
            issuer: frozenset(authorities)
            for issuer, authorities in recognized_requirement_issuers.items()
        }
        self.validator = validator or CapabilityContractValidator()

    def resolve(
        self,
        *,
        requirements: Sequence[Mapping[str, Any]],
        validity_scope: Mapping[str, Any],
        condition_values: Mapping[str, Any],
        evaluated_at: datetime,
    ) -> RequirementResolution:
        _aware_utc(evaluated_at, "evaluated_at")
        if not requirements:
            raise ResolutionInputError("at least one requirement is required")
        if not _is_scope(validity_scope):
            raise ResolutionInputError("validity_scope must be explicit")

        ordered = sorted((dict(item) for item in requirements), key=_requirement_key)
        findings: list[ResolutionFinding] = []
        rejected: dict[str, Mapping[str, Any]] = {}
        admitted: dict[str, Mapping[str, Any]] = {}

        for requirement in ordered:
            requirement_id = str(requirement.get("requirement_id", "<unknown>"))
            validation = self.validator.validate(requirement)
            if not validation.valid or requirement.get("entity_type") != "capability_requirement":
                rejected[requirement_id] = requirement
                findings.append(
                    ResolutionFinding(
                        "INVALID_REQUIREMENT",
                        requirement_id,
                        "; ".join(validation.errors) or "Wrong entity type",
                    )
                )
                continue
            if not self._authority_is_recognized(requirement):
                rejected[requirement_id] = requirement
                findings.append(
                    ResolutionFinding(
                        "AUTHORITY_UNRECOGNIZED",
                        requirement_id,
                        "Issuer authority is absent or not recognized",
                    )
                )
                continue
            if requirement["validity_scope"] != validity_scope:
                rejected[requirement_id] = requirement
                findings.append(
                    ResolutionFinding(
                        "SCOPE_NOT_APPLICABLE",
                        requirement_id,
                        "Requirement scope does not exactly match resolution scope",
                    )
                )
                continue
            condition_state = _conditions_apply(requirement["conditions"], condition_values)
            if condition_state is None:
                rejected[requirement_id] = requirement
                findings.append(
                    ResolutionFinding(
                        "CONDITION_UNRESOLVED",
                        requirement_id,
                        "A condition value is missing",
                    )
                )
                continue
            if not condition_state:
                rejected[requirement_id] = requirement
                findings.append(
                    ResolutionFinding(
                        "CONDITION_NOT_MET",
                        requirement_id,
                        "Declared conditions do not apply",
                    )
                )
                continue
            admitted[requirement_id] = requirement

        supersession_unresolved = self._apply_supersession(
            admitted, rejected, findings
        )

        effective: list[Mapping[str, Any]] = []
        unresolved: list[Mapping[str, Any]] = list(supersession_unresolved)
        groups: dict[str, list[Mapping[str, Any]]] = {}
        for requirement in admitted.values():
            groups.setdefault(requirement["capability"]["id"], []).append(requirement)

        for capability_id in sorted(groups):
            group = sorted(groups[capability_id], key=_requirement_key)
            hard = [item for item in group if item["strength"] in {"required", "prohibited"}]
            hard_strengths = {item["strength"] for item in hard}
            required_versions = {
                item["capability"]["version"]
                for item in hard
                if item["strength"] == "required"
            }
            if hard_strengths == {"required", "prohibited"}:
                conflict = _reasoned_capability(capability_id, "required_prohibited_conflict")
                unresolved.append(conflict)
                for item in group:
                    findings.append(
                        ResolutionFinding(
                            "HARD_REQUIREMENT_CONFLICT",
                            item["requirement_id"],
                            "Required and prohibited declarations remain simultaneously authoritative",
                        )
                    )
                continue
            if len(required_versions) > 1:
                conflict = _reasoned_capability(capability_id, "required_version_conflict")
                unresolved.append(conflict)
                for item in hard:
                    findings.append(
                        ResolutionFinding(
                            "HARD_VERSION_CONFLICT",
                            item["requirement_id"],
                            "Multiple exact required versions remain authoritative",
                        )
                    )
                continue
            if "prohibited" in hard_strengths:
                effective.extend(hard)
                for item in group:
                    if item["strength"] != "prohibited":
                        rejected[item["requirement_id"]] = item
                        findings.append(
                            ResolutionFinding(
                                "PROHIBITION_DOMINATES_SOFT_REQUIREMENT",
                                item["requirement_id"],
                                "An authoritative prohibition dominates a soft declaration",
                            )
                        )
                continue
            effective.extend(group)

        effective.sort(key=_requirement_key)
        unresolved.sort(key=lambda item: _reference_key(item["subject"]))
        rejected_items = tuple(rejected[key] for key in sorted(rejected))
        input_refs = [_requirement_reference(item) for item in ordered]
        output_refs = [_requirement_reference(item) for item in effective]
        record = {
            "schema": "capability-definition.v1",
            "entity_type": "resolution_result",
            "resolution_id": _stable_identifier(
                "resolution.requirements", input_refs, validity_scope, condition_values
            ),
            "resolution_kind": "capability_requirement_reconciliation",
            "inputs": input_refs,
            "method": dict(self.METHOD),
            "derived_outputs": output_refs,
            "rejected_inputs": [
                {
                    "subject": _requirement_reference(item),
                    "reason_codes": sorted(
                        {
                            finding.code.lower()
                            for finding in findings
                            if finding.subject_id == item["requirement_id"]
                        }
                    )
                    or ["not_effective"],
                }
                for item in rejected_items
            ],
            "unresolved": unresolved,
            "issuer": self.resolver_id,
            "limitations": [
                "Scope applicability is exact; v1 does not infer scope inheritance",
                "Authority precedence is explicit; v1 does not infer an authority hierarchy",
            ],
            "validity_scope": dict(validity_scope),
            "supersession": None,
        }
        validation = self.validator.validate(record)
        if not validation.valid:
            raise ResolutionInputError(
                "resolver produced an invalid ResolutionResult: "
                + "; ".join(validation.errors)
            )
        return RequirementResolution(
            tuple(effective),
            rejected_items,
            tuple(sorted(findings, key=lambda item: (item.subject_id, item.code))),
            tuple(unresolved),
            record,
        )

    def _authority_is_recognized(self, requirement: Mapping[str, Any]) -> bool:
        authority = requirement.get("authority_binding")
        return bool(
            _is_reference(authority)
            and authority.get("semantic_type") == "authority_binding"
            and authority["id"]
            in self.recognized_requirement_issuers.get(requirement["issuer"], ())
        )

    @staticmethod
    def _apply_supersession(
        admitted: dict[str, Mapping[str, Any]],
        rejected: dict[str, Mapping[str, Any]],
        findings: list[ResolutionFinding],
    ) -> list[Mapping[str, Any]]:
        unresolved: list[Mapping[str, Any]] = []
        superseders: dict[str, list[Mapping[str, Any]]] = {}
        for requirement in admitted.values():
            prior = requirement.get("supersession")
            if _is_reference(prior) and prior.get("semantic_type") == "capability_requirement":
                superseders.setdefault(prior["id"], []).append(requirement)

        for prior_id in sorted(superseders):
            candidates = superseders[prior_id]
            prior = admitted.get(prior_id)
            if prior is None:
                continue
            authorized = [
                item
                for item in candidates
                if item["issuer"] == prior["issuer"] or item["source_class"] == "override"
            ]
            if len(authorized) != 1:
                for item in candidates:
                    findings.append(
                        ResolutionFinding(
                            "SUPERSESSION_AMBIGUOUS",
                            item["requirement_id"],
                            "Supersession is not uniquely attributable",
                        )
                    )
                    rejected[item["requirement_id"]] = admitted.pop(
                        item["requirement_id"]
                    )
                rejected[prior_id] = admitted.pop(prior_id)
                unresolved.append(
                    _reasoned_capability(
                        prior["capability"]["id"], "supersession_ambiguous"
                    )
                )
                continue
            rejected[prior_id] = admitted.pop(prior_id)
            findings.append(
                ResolutionFinding(
                    "REQUIREMENT_SUPERSEDED",
                    prior_id,
                    f"Superseded by {authorized[0]['requirement_id']}",
                )
            )
        return unresolved


class CandidateResolver:
    """Admit candidates from supplied facts without ranking or selecting them."""

    def __init__(
        self,
        *,
        recognized_claim_issuers: Mapping[str, set[str] | frozenset[str]],
        recognized_assessment_issuers: Mapping[str, set[str] | frozenset[str]],
        validator: CapabilityContractValidator | None = None,
    ) -> None:
        self.validator = validator or CapabilityContractValidator()
        self.recognized_claim_issuers = {
            issuer: frozenset(authorities)
            for issuer, authorities in recognized_claim_issuers.items()
        }
        self.recognized_assessment_issuers = {
            issuer: frozenset(authorities)
            for issuer, authorities in recognized_assessment_issuers.items()
        }

    def resolve(
        self,
        *,
        requirement: Mapping[str, Any],
        requirement_resolution: RequirementResolution,
        capability: Mapping[str, Any],
        candidates: Sequence[CandidateFacts],
        evaluated_at: datetime,
    ) -> CandidateResolution:
        evaluated_at = _aware_utc(evaluated_at, "evaluated_at")
        if requirement not in requirement_resolution.effective_requirements:
            raise ResolutionInputError("requirement is not effective in the supplied resolution")
        if requirement["strength"] == "prohibited":
            raise ResolutionInputError("a prohibited requirement admits no candidates")
        for document, expected in (
            (requirement, "capability_requirement"),
            (capability, "capability_definition"),
        ):
            validation = self.validator.validate(document)
            if not validation.valid or document.get("entity_type") != expected:
                raise ResolutionInputError(f"invalid {expected}")

        capability_ref = _capability_reference(capability)
        if not _same_reference(requirement["capability"], capability_ref):
            raise ResolutionInputError("requirement and capability definition do not match exactly")

        eligible: list[Mapping[str, Any]] = []
        rejected: list[Mapping[str, Any]] = []
        findings: list[ResolutionFinding] = []
        all_claims: list[Mapping[str, Any]] = []
        compatibility_refs: list[Mapping[str, Any]] = []
        constraint_refs: list[Mapping[str, Any]] = []
        risk_refs: list[Mapping[str, Any]] = []

        for facts in sorted(candidates, key=lambda item: _implementation_key(item.implementation)):
            implementation = facts.implementation
            implementation_ref = _implementation_reference(implementation)
            reasons = self._candidate_reasons(
                requirement=requirement,
                capability=capability,
                facts=facts,
                validity_scope=requirement["validity_scope"],
                evaluated_at=evaluated_at,
            )
            all_claims.extend(facts.conformance_claims)
            compatibility_refs.extend(item.reference for item in facts.compatibility)
            constraint_refs.extend(item.reference for item in facts.constraints)
            risk_refs.extend(facts.risk_assessments)
            if reasons:
                rejected.append(
                    {"subject": implementation_ref, "reason_codes": sorted(set(reasons))}
                )
                findings.extend(
                    ResolutionFinding(code.upper(), implementation["implementation_id"], code)
                    for code in sorted(set(reasons))
                )
            else:
                eligible.append(implementation_ref)

        eligible.sort(key=_reference_key)
        rejected.sort(key=lambda item: _reference_key(item["subject"]))
        unresolved = tuple(requirement_resolution.unresolved)
        policy_input = PolicyInputPackage(
            requirement=_requirement_reference(requirement),
            resolution=_resolution_reference(requirement_resolution.record),
            eligible_candidates=tuple(eligible),
            rejected_candidates=tuple(rejected),
            conformance_claims=tuple(_unique_references(_claim_reference(item) for item in all_claims)),
            compatibility_assessments=tuple(_unique_references(compatibility_refs)),
            constraint_assessments=tuple(_unique_references(constraint_refs)),
            risk_assessments=tuple(_unique_references(risk_refs)),
            unresolved=unresolved,
            limitations=("Candidate admission does not imply selection, policy, or binding",),
        )
        return CandidateResolution(tuple(eligible), tuple(rejected), tuple(findings), policy_input)

    def _candidate_reasons(
        self,
        *,
        requirement: Mapping[str, Any],
        capability: Mapping[str, Any],
        facts: CandidateFacts,
        validity_scope: Mapping[str, Any],
        evaluated_at: datetime,
    ) -> list[str]:
        implementation = facts.implementation
        validation = self.validator.validate(implementation)
        if not validation.valid or implementation.get("entity_type") != "implementation_descriptor":
            return ["invalid_implementation_descriptor"]
        if implementation["lifecycle_status"] == "withdrawn":
            return ["implementation_withdrawn"]
        if not any(
            _same_reference(requirement["capability"], declared)
            for declared in implementation["declared_capabilities"]
        ):
            return ["capability_not_declared"]

        implementation_ref = _implementation_reference(implementation)
        capability_ref = _capability_reference(capability)
        claim_by_dimension: dict[str, list[Mapping[str, Any]]] = {}
        reasons: list[str] = []
        for claim in facts.conformance_claims:
            claim_validation = self.validator.validate(claim)
            if not claim_validation.valid or claim.get("entity_type") != "conformance_claim":
                reasons.append("invalid_conformance_claim")
                continue
            if not _same_reference(claim["subject"], implementation_ref) or not _same_reference(
                claim["capability"], capability_ref
            ):
                reasons.append("conformance_subject_mismatch")
                continue
            if not self._authority_recognized(
                claim["issuer"], claim["authority_binding"], self.recognized_claim_issuers
            ):
                reasons.append("conformance_authority_unrecognized")
                continue
            if claim["validity"]["scope"] != validity_scope:
                reasons.append("conformance_scope_mismatch")
                continue
            valid_until = claim["validity"]["valid_until"]
            if valid_until is not None and evaluated_at > _parse_time(
                valid_until, "claim valid_until"
            ):
                reasons.append("conformance_expired")
                continue
            claim_by_dimension.setdefault(claim["dimension"], []).append(claim)
        for dimension in capability["conformance_requirements"]:
            claims = claim_by_dimension.get(dimension, [])
            if len(claims) != 1:
                reasons.append(f"conformance_{dimension}_ambiguous_or_missing")
            elif claims[0]["outcome"] != "satisfied":
                reasons.append(f"conformance_{dimension}_{claims[0]['outcome']}")

        if not facts.compatibility:
            reasons.append("compatibility_missing")
        for fact in facts.compatibility:
            if not _is_typed_reference(fact.reference, "compatibility_assessment"):
                reasons.append("invalid_compatibility_reference")
            elif not self._fact_is_governed(fact):
                reasons.append("compatibility_fact_untrusted")
            elif fact.validity_scope != validity_scope:
                reasons.append("compatibility_scope_mismatch")
            elif fact.valid_until is not None and evaluated_at > _aware_utc(
                fact.valid_until, "compatibility valid_until"
            ):
                reasons.append("compatibility_expired")
            elif fact.outcome != "compatible":
                reasons.append(f"compatibility_{fact.outcome}")
        if requirement["constraints"] and not facts.constraints:
            reasons.append("constraint_missing")
        for fact in facts.constraints:
            if not _is_reference(fact.reference) or fact.reference["semantic_type"] not in {
                "constraint_assessment",
                "constraint_reference",
            }:
                reasons.append("invalid_constraint_reference")
            elif not self._fact_is_governed(fact):
                reasons.append("constraint_fact_untrusted")
            elif fact.validity_scope != validity_scope:
                reasons.append("constraint_scope_mismatch")
            elif fact.valid_until is not None and evaluated_at > _aware_utc(
                fact.valid_until, "constraint valid_until"
            ):
                reasons.append("constraint_expired")
            elif fact.outcome != "satisfied":
                reasons.append(f"constraint_{fact.outcome}")
        return reasons

    def _fact_is_governed(self, fact: AssessedFact) -> bool:
        return bool(
            self._authority_recognized(
                fact.issuer,
                fact.authority_binding,
                self.recognized_assessment_issuers,
            )
            and fact.digest == fact.expected_digest()
        )

    @staticmethod
    def _authority_recognized(
        issuer: str,
        authority: Mapping[str, Any],
        recognized: Mapping[str, frozenset[str]],
    ) -> bool:
        return bool(
            _is_typed_reference(authority, "authority_binding")
            and authority["id"] in recognized.get(issuer, ())
        )


def _conditions_apply(
    conditions: Sequence[Mapping[str, Any]], values: Mapping[str, Any]
) -> bool | None:
    for condition in conditions:
        key = _reference_key(condition["subject"])
        if key not in values:
            return None
        actual = values[key]
        operator = condition["operator"]
        expected = condition.get("value")
        if operator == "exists":
            result = bool(actual is not None) if expected is None else bool(actual is not None) == bool(expected)
        elif operator == "equals":
            result = actual == expected
        elif operator == "not_equals":
            result = actual != expected
        else:
            result = actual in expected if isinstance(expected, (list, tuple, set)) else False
        if not result:
            return False
    return True


def _requirement_key(requirement: Mapping[str, Any]) -> tuple[str, str]:
    capability = requirement.get("capability") or {}
    return str(capability.get("id", "")), str(requirement.get("requirement_id", ""))


def _implementation_key(implementation: Mapping[str, Any]) -> tuple[str, str]:
    return str(implementation.get("implementation_id", "")), str(implementation.get("version", ""))


def _reference_key(reference: Mapping[str, Any]) -> str:
    return f"{reference.get('semantic_type', '')}:{reference.get('id', '')}:{reference.get('version', '')}"


def _is_reference(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(value.get(field), str) and value[field]
        for field in ("semantic_type", "id", "version")
    )


def _same_reference(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Compare semantic identity; issuer metadata is not part of reference identity."""

    return all(left.get(field) == right.get(field) for field in ("semantic_type", "id", "version")) and (
        left.get("digest") is None
        or right.get("digest") is None
        or left.get("digest") == right.get("digest")
    )


def _is_typed_reference(value: Any, semantic_type: str) -> bool:
    return _is_reference(value) and value["semantic_type"] == semantic_type


def _is_scope(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(value.get(field), str) and value[field]
        for field in ("scope_type", "scope_id")
    )


def _requirement_reference(requirement: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"semantic_type": "capability_requirement", "id": requirement["requirement_id"], "version": "1.0.0", "issuer": requirement["issuer"]}


def _capability_reference(capability: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"semantic_type": "capability", "id": capability["capability_id"], "version": capability["version"], "issuer": capability["issuer"]}


def _implementation_reference(implementation: Mapping[str, Any]) -> Mapping[str, Any]:
    reference: dict[str, Any] = {"semantic_type": "implementation", "id": implementation["implementation_id"], "version": implementation["version"], "issuer": implementation["issuer"]}
    if implementation.get("digest") is not None:
        reference["digest"] = implementation["digest"]
    return reference


def _resolution_reference(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"semantic_type": "resolution_result", "id": record["resolution_id"], "version": "1.0.0", "issuer": record["issuer"]}


def _claim_reference(claim: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"semantic_type": "conformance_claim", "id": claim["claim_id"], "version": "1.0.0", "issuer": claim["issuer"]}


def _reasoned_capability(capability_id: str, reason: str) -> Mapping[str, Any]:
    return {"subject": {"semantic_type": "capability", "id": capability_id, "version": "unresolved"}, "reason_codes": [reason]}


def _unique_references(references: Sequence[Mapping[str, Any]] | Any) -> list[Mapping[str, Any]]:
    unique: dict[str, Mapping[str, Any]] = {}
    for reference in references:
        unique[_reference_key(reference)] = dict(reference)
    return [unique[key] for key in sorted(unique)]


def _stable_identifier(prefix: str, *parts: Any) -> str:
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{prefix}.{hashlib.sha256(encoded).hexdigest()[:20]}"


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResolutionInputError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_time(value: str, name: str) -> datetime:
    try:
        return _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")), name)
    except ValueError as error:
        raise ResolutionInputError(f"{name} is invalid") from error
