"""Governed planning of proposed capability bindings.

The planner consumes an external policy fact. It does not evaluate policy,
activate a binding, provision, deploy, or execute anything.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping

from .conformance import CapabilityContractValidator
from .resolution import AssessedFact, CandidateFacts


PolicyOutcome = Literal["ALLOW", "DENY", "REVIEW_REQUIRED", "CONDITIONAL"]


class BindingInputError(ValueError):
    """Raised when governed binding prerequisites are invalid or incomplete."""


@dataclass(frozen=True)
class PolicyDecisionFact:
    """Materialized external policy decision consumed by the binding planner."""

    reference: Mapping[str, Any]
    subject: Mapping[str, Any]
    outcome: PolicyOutcome
    supports: tuple[Mapping[str, Any], ...]
    issuer: str
    authority_binding: Mapping[str, Any]
    validity_scope: Mapping[str, Any]
    issued_at: datetime
    effective_from: datetime | None = None
    valid_until: datetime | None = None
    revoked_at: datetime | None = None
    digest: str = ""

    def expected_digest(self) -> str:
        material = {
            "reference": dict(self.reference),
            "subject": dict(self.subject),
            "outcome": self.outcome,
            "supports": [dict(item) for item in self.supports],
            "issuer": self.issuer,
            "authority_binding": dict(self.authority_binding),
            "validity_scope": dict(self.validity_scope),
            "issued_at": self.issued_at.isoformat(),
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class BindingPlan:
    binding: Mapping[str, Any]
    direct_supports: tuple[Mapping[str, Any], ...]
    policy_decision: Mapping[str, Any]
    limitations: tuple[str, ...]


class BindingPlanner:
    """Validate exact prerequisites and emit a proposed binding only."""

    def __init__(
        self,
        *,
        issuer: str,
        authority_binding: Mapping[str, Any],
        recognized_policy_issuers: Mapping[str, set[str] | frozenset[str]],
        recognized_claim_issuers: Mapping[str, set[str] | frozenset[str]],
        recognized_assessment_issuers: Mapping[str, set[str] | frozenset[str]],
        allowed_clock_skew: timedelta = timedelta(0),
        validator: CapabilityContractValidator | None = None,
    ) -> None:
        if not issuer:
            raise BindingInputError("issuer is required")
        if not _is_typed_reference(authority_binding, "authority_binding"):
            raise BindingInputError("binding authority must be explicit")
        if allowed_clock_skew < timedelta(0):
            raise BindingInputError("allowed_clock_skew cannot be negative")
        self.issuer = issuer
        self.authority_binding = dict(authority_binding)
        self.recognized_policy_issuers = {
            item_issuer: frozenset(authorities)
            for item_issuer, authorities in recognized_policy_issuers.items()
        }
        self.recognized_claim_issuers = {
            item_issuer: frozenset(authorities)
            for item_issuer, authorities in recognized_claim_issuers.items()
        }
        self.recognized_assessment_issuers = {
            item_issuer: frozenset(authorities)
            for item_issuer, authorities in recognized_assessment_issuers.items()
        }
        self.allowed_clock_skew = allowed_clock_skew
        self.validator = validator or CapabilityContractValidator()

    def plan(
        self,
        *,
        binding_id: str,
        requirement: Mapping[str, Any],
        capability: Mapping[str, Any],
        selection_result: Mapping[str, Any],
        selected: CandidateFacts,
        policy_decision: PolicyDecisionFact,
        validity_scope: Mapping[str, Any],
        evaluated_at: datetime,
        risk_assessment: Mapping[str, Any] | None = None,
    ) -> BindingPlan:
        evaluated_at = _aware_utc(evaluated_at, "evaluated_at")
        if not binding_id:
            raise BindingInputError("binding_id is required")
        if not _is_scope(validity_scope):
            raise BindingInputError("validity_scope must be explicit")
        self._validate_document(requirement, "capability_requirement")
        self._validate_document(capability, "capability_definition")
        self._validate_document(selection_result, "selection_result")
        self._validate_document(selected.implementation, "implementation_descriptor")

        requirement_ref = _requirement_reference(requirement)
        capability_ref = _capability_reference(capability)
        implementation_ref = _implementation_reference(selected.implementation)
        selection_ref = _selection_reference(selection_result)
        if selection_result["outcome"] != "selected":
            raise BindingInputError("selection outcome must be selected")
        if selection_result["unresolved"]:
            raise BindingInputError("selection contains unresolved alternatives or conflicts")
        if selection_result["requirement"] != requirement_ref:
            raise BindingInputError("selection does not reference the exact requirement")
        if selection_result["selected_candidate"] != implementation_ref:
            raise BindingInputError("selection does not reference the exact implementation")
        if not _same_reference(requirement["capability"], capability_ref):
            raise BindingInputError("requirement and capability do not match exactly")
        if implementation_ref not in selection_result["eligible_candidates"]:
            raise BindingInputError("selected implementation was not eligible")
        if requirement["strength"] == "prohibited":
            raise BindingInputError("a prohibited requirement cannot be bound")
        if selected.implementation["lifecycle_status"] == "withdrawn":
            raise BindingInputError("a withdrawn implementation cannot be bound")
        if not selected.compatibility:
            raise BindingInputError("compatibility assessment is required")
        if requirement["constraints"] and not selected.constraints:
            raise BindingInputError("required constraint assessments are missing")

        claim_refs = self._validate_claims(
            selected=selected,
            capability=capability,
            capability_ref=capability_ref,
            implementation_ref=implementation_ref,
            validity_scope=validity_scope,
            evaluated_at=evaluated_at,
        )
        compatibility_refs = self._validate_assessed_facts(
            selected.compatibility,
            expected="compatible",
            label="compatibility",
            validity_scope=validity_scope,
            evaluated_at=evaluated_at,
        )
        constraint_refs = self._validate_assessed_facts(
            selected.constraints,
            expected="satisfied",
            label="constraint",
            validity_scope=validity_scope,
            evaluated_at=evaluated_at,
        )
        self._validate_policy(
            policy_decision,
            selection_ref=selection_ref,
            validity_scope=validity_scope,
            evaluated_at=evaluated_at,
        )
        if risk_assessment is not None and not _is_reference(risk_assessment):
            raise BindingInputError("risk_assessment must be a reference or null")

        contracts = tuple(
            sorted(
                (dict(item) for item in selected.implementation["supported_contracts"]),
                key=_reference_key,
            )
        )
        if not contracts:
            raise BindingInputError("selected implementation must declare supported contracts")
        binding = {
            "schema": "capability-definition.v1",
            "entity_type": "capability_binding",
            "binding_id": binding_id,
            "requirement": requirement_ref,
            "capability": capability_ref,
            "implementation": implementation_ref,
            "contracts": list(contracts),
            "selection_result": selection_ref,
            "conformance_claims": list(claim_refs),
            "constraints": list(constraint_refs),
            "risk_assessment": dict(risk_assessment) if risk_assessment else None,
            "policy_decision": dict(policy_decision.reference),
            "issuer": self.issuer,
            "authority_binding": dict(self.authority_binding),
            "validity_scope": dict(validity_scope),
            "lifecycle_status": "proposed",
            "supersession": None,
        }
        validation = self.validator.validate(binding)
        if not validation.valid:
            raise BindingInputError(
                "planner produced an invalid CapabilityBinding: "
                + "; ".join(validation.errors)
            )

        direct_supports = _unique_references(
            [
                selection_ref,
                *claim_refs,
                *compatibility_refs,
                *constraint_refs,
                policy_decision.reference,
                *([risk_assessment] if risk_assessment else []),
            ]
        )
        return BindingPlan(
            binding=binding,
            direct_supports=tuple(direct_supports),
            policy_decision=dict(policy_decision.reference),
            limitations=(
                "The binding is proposed and has not been activated",
                "The planner consumed policy; it did not evaluate or issue policy",
            ),
        )

    def _validate_document(self, document: Mapping[str, Any], entity_type: str) -> None:
        validation = self.validator.validate(document)
        if not validation.valid or document.get("entity_type") != entity_type:
            raise BindingInputError(
                f"invalid {entity_type}: " + "; ".join(validation.errors)
            )

    def _validate_claims(
        self,
        *,
        selected: CandidateFacts,
        capability: Mapping[str, Any],
        capability_ref: Mapping[str, Any],
        implementation_ref: Mapping[str, Any],
        validity_scope: Mapping[str, Any],
        evaluated_at: datetime,
    ) -> tuple[Mapping[str, Any], ...]:
        by_dimension: dict[str, list[Mapping[str, Any]]] = {}
        for claim in selected.conformance_claims:
            self._validate_document(claim, "conformance_claim")
            if not _same_reference(claim["subject"], implementation_ref) or not _same_reference(
                claim["capability"], capability_ref
            ):
                raise BindingInputError("conformance claim subject mismatch")
            if not self._authority_recognized(
                claim["issuer"], claim["authority_binding"], self.recognized_claim_issuers
            ):
                raise BindingInputError("conformance claim authority is not recognized")
            if claim["validity"]["scope"] != validity_scope:
                raise BindingInputError("conformance claim scope mismatch")
            valid_until = claim["validity"]["valid_until"]
            if valid_until is not None and evaluated_at - self.allowed_clock_skew > _parse_time(valid_until, "claim valid_until"):
                raise BindingInputError("conformance claim is expired")
            by_dimension.setdefault(claim["dimension"], []).append(claim)

        references: list[Mapping[str, Any]] = []
        for dimension in capability["conformance_requirements"]:
            claims = by_dimension.get(dimension, [])
            if len(claims) != 1 or claims[0]["outcome"] != "satisfied":
                raise BindingInputError(
                    f"dimension {dimension} requires one current satisfied claim"
                )
            references.append(_claim_reference(claims[0]))
        return tuple(sorted(references, key=_reference_key))

    def _validate_assessed_facts(
        self,
        facts: tuple[AssessedFact, ...], *, expected: str, label: str
        , validity_scope: Mapping[str, Any], evaluated_at: datetime
    ) -> tuple[Mapping[str, Any], ...]:
        references: list[Mapping[str, Any]] = []
        for fact in facts:
            allowed_types = (
                {"compatibility_assessment"}
                if label == "compatibility"
                else {"constraint_assessment", "constraint_reference"}
            )
            if (
                not _is_reference(fact.reference)
                or fact.reference["semantic_type"] not in allowed_types
            ):
                raise BindingInputError(f"invalid {label} assessment reference")
            if fact.validity_scope != validity_scope:
                raise BindingInputError(f"{label} assessment scope mismatch")
            if not self._authority_recognized(
                fact.issuer,
                fact.authority_binding,
                self.recognized_assessment_issuers,
            ):
                raise BindingInputError(f"{label} assessment authority is not recognized")
            if fact.digest != fact.expected_digest():
                raise BindingInputError(f"{label} assessment digest mismatch")
            if (
                fact.valid_until is not None
                and evaluated_at - self.allowed_clock_skew
                > _aware_utc(fact.valid_until, f"{label} valid_until")
            ):
                raise BindingInputError(f"{label} assessment is expired")
            if fact.outcome != expected:
                raise BindingInputError(f"{label} outcome is {fact.outcome}, not {expected}")
            references.append(dict(fact.reference))
        return tuple(sorted(references, key=_reference_key))

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

    def _validate_policy(
        self,
        decision: PolicyDecisionFact,
        *,
        selection_ref: Mapping[str, Any],
        validity_scope: Mapping[str, Any],
        evaluated_at: datetime,
    ) -> None:
        if not _is_typed_reference(decision.reference, "policy_decision"):
            raise BindingInputError("policy decision reference is invalid")
        if decision.subject != selection_ref:
            raise BindingInputError("policy decision is not bound to the exact selection")
        if decision.outcome != "ALLOW":
            raise BindingInputError(f"policy outcome {decision.outcome} cannot authorize binding")
        if decision.validity_scope != validity_scope:
            raise BindingInputError("policy decision scope mismatch")
        if not _is_typed_reference(decision.authority_binding, "authority_binding"):
            raise BindingInputError("policy authority is absent")
        recognized = self.recognized_policy_issuers.get(decision.issuer, ())
        if decision.authority_binding["id"] not in recognized:
            raise BindingInputError("policy issuer authority is not recognized")
        if not decision.supports:
            raise BindingInputError("policy decision has no direct supports")
        if decision.digest != decision.expected_digest():
            raise BindingInputError("policy decision digest mismatch")
        issued_at = _aware_utc(decision.issued_at, "policy issued_at")
        if issued_at - self.allowed_clock_skew > evaluated_at:
            raise BindingInputError("policy decision was issued in the future")
        if decision.effective_from is not None and _aware_utc(decision.effective_from, "policy effective_from") - self.allowed_clock_skew > evaluated_at:
            raise BindingInputError("policy decision is not yet effective")
        if decision.valid_until is not None and evaluated_at - self.allowed_clock_skew > _aware_utc(decision.valid_until, "policy valid_until"):
            raise BindingInputError("policy decision is expired")
        if decision.revoked_at is not None and _aware_utc(decision.revoked_at, "policy revoked_at") <= evaluated_at + self.allowed_clock_skew:
            raise BindingInputError("policy decision is revoked")


def _is_reference(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(value.get(field), str) and value[field]
        for field in ("semantic_type", "id", "version")
    )


def _is_typed_reference(value: Any, semantic_type: str) -> bool:
    return _is_reference(value) and value["semantic_type"] == semantic_type


def _same_reference(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(left.get(field) == right.get(field) for field in ("semantic_type", "id", "version")) and (
        left.get("digest") is None
        or right.get("digest") is None
        or left.get("digest") == right.get("digest")
    )


def _is_scope(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(value.get(field), str) and value[field]
        for field in ("scope_type", "scope_id")
    )


def _reference_key(reference: Mapping[str, Any]) -> str:
    return f"{reference.get('semantic_type', '')}:{reference.get('id', '')}:{reference.get('version', '')}"


def _requirement_reference(requirement: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"semantic_type": "capability_requirement", "id": requirement["requirement_id"], "version": "1.0.0", "issuer": requirement["issuer"]}


def _capability_reference(capability: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"semantic_type": "capability", "id": capability["capability_id"], "version": capability["version"], "issuer": capability["issuer"]}


def _implementation_reference(implementation: Mapping[str, Any]) -> Mapping[str, Any]:
    reference: dict[str, Any] = {"semantic_type": "implementation", "id": implementation["implementation_id"], "version": implementation["version"], "issuer": implementation["issuer"]}
    if implementation.get("digest") is not None:
        reference["digest"] = implementation["digest"]
    return reference


def _selection_reference(selection: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"semantic_type": "selection_result", "id": selection["selection_id"], "version": "1.0.0", "issuer": selection["issuer"]}


def _claim_reference(claim: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"semantic_type": "conformance_claim", "id": claim["claim_id"], "version": "1.0.0", "issuer": claim["issuer"]}


def _unique_references(references: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    unique = {_reference_key(item): dict(item) for item in references}
    return [unique[key] for key in sorted(unique)]


def _parse_time(value: str, name: str) -> datetime:
    try:
        return _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")), name)
    except ValueError as error:
        raise BindingInputError(f"{name} is invalid") from error


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BindingInputError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
