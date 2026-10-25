import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from capabilities.binding import BindingInputError, BindingPlanner, PolicyDecisionFact
from capabilities.conformance import CapabilityContractValidator
from capabilities.resolution import (
    AssessedFact,
    CandidateFacts,
    CandidateResolver,
    RequirementResolver,
    ResolutionInputError,
)


NOW = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)
SCOPE = {"scope_type": "project", "scope_id": "fixture.step6"}


def ref(semantic_type, identifier, version="1.0.0", **extra):
    return {"semantic_type": semantic_type, "id": identifier, "version": version, **extra}


AUTHORITY = ref("authority_binding", "authority.requirements")
CAPABILITY_AUTHORITY = ref("authority_binding", "authority.capability")
IMPLEMENTATION_AUTHORITY = ref("authority_binding", "authority.implementation")
EVALUATION_AUTHORITY = ref("authority_binding", "authority.evaluation")
ASSESSMENT_AUTHORITY = ref("authority_binding", "authority.assessment")
BINDING_AUTHORITY = ref("authority_binding", "authority.binding")
POLICY_AUTHORITY = ref("authority_binding", "authority.policy")


def requirement(
    identifier="requirement.compile",
    *,
    version="1.0.0",
    strength="required",
    issuer="fixture.project",
    authority=AUTHORITY,
    source_class="project",
    scope=SCOPE,
    conditions=(),
    supersession=None,
):
    return {
        "schema": "capability-definition.v1",
        "entity_type": "capability_requirement",
        "requirement_id": identifier,
        "capability": ref("capability", "engineering.compile", version),
        "profile_requirements": [],
        "strength": strength,
        "issuer": issuer,
        "authority_binding": authority,
        "source_class": source_class,
        "validity_scope": scope,
        "conditions": list(conditions),
        "constraints": [],
        "policy_requirements": [],
        "compatibility_expectations": [],
        "supersession": supersession,
    }


def capability():
    return {
        "schema": "capability-definition.v1",
        "entity_type": "capability_definition",
        "capability_id": "engineering.compile",
        "version": "1.0.0",
        "lifecycle_status": "stable",
        "classification": "platform_baseline",
        "semantic_description": "Compile governed source artifacts.",
        "responsibilities": ["Compile source"],
        "non_responsibilities": ["Authorize release"],
        "semantic_operations": ["Execution", "Evaluation"],
        "input_contracts": [ref("contract", "source.v1")],
        "output_contracts": [ref("contract", "binary.v1")],
        "relationships": [],
        "profiles": [],
        "policy_requirements": [],
        "constraint_requirements": [],
        "conformance_requirements": ["structural", "semantic", "behavioral", "operational"],
        "compatibility_policy": ref("compatibility_policy", "compat.compile"),
        "issuer": "fixture.capability-owner",
        "authority_binding": CAPABILITY_AUTHORITY,
        "validity_scope": SCOPE,
        "supersession": None,
    }


def implementation(identifier="implementation.compiler", status="stable"):
    return {
        "schema": "capability-definition.v1",
        "entity_type": "implementation_descriptor",
        "implementation_id": identifier,
        "version": "1.0.0",
        "digest": f"sha256:{identifier}",
        "lifecycle_status": status,
        "roles": ["compile_time"],
        "declared_capabilities": [ref("capability", "engineering.compile")],
        "supported_contracts": [ref("contract", "source.v1"), ref("contract", "binary.v1")],
        "operating_constraints": [],
        "resource_characteristics": [],
        "required_capabilities": [],
        "credential_references": [],
        "compatibility_declarations": [],
        "issuer": "fixture.implementation-owner",
        "authority_binding": IMPLEMENTATION_AUTHORITY,
        "validity_scope": SCOPE,
        "supersession": None,
    }


def claim(impl, dimension, outcome="satisfied", valid_until=None):
    return {
        "schema": "capability-definition.v1",
        "entity_type": "conformance_claim",
        "claim_id": f"claim.{impl['implementation_id']}.{dimension}",
        "subject": ref(
            "implementation",
            impl["implementation_id"],
            impl["version"],
            digest=impl["digest"],
            issuer=impl["issuer"],
        ),
        "capability": ref("capability", "engineering.compile", issuer="fixture.capability-owner"),
        "contracts": [ref("contract", "source.v1")],
        "dimension": dimension,
        "outcome": outcome,
        "method": ref("evaluation_definition", f"eval.{dimension}"),
        "environment": ref("environment", "fixture.environment"),
        "supports": [ref("evidence_record", f"evidence.{dimension}")],
        "issuer": "fixture.evaluator",
        "authority_binding": EVALUATION_AUTHORITY,
        "assessment_time": NOW.isoformat(),
        "validity": {"scope": SCOPE, "valid_until": valid_until.isoformat() if valid_until else None},
        "limitations": [],
        "supersession": None,
    }


def candidate_facts(impl=None, compatibility="compatible", constraint="satisfied"):
    impl = impl or implementation()
    claims = tuple(
        claim(impl, dimension)
        for dimension in ("structural", "semantic", "behavioral", "operational")
    )
    compatibility_fact = AssessedFact(
        ref("compatibility_assessment", f"compat.{impl['implementation_id']}"),
        compatibility,
        "fixture.assessor",
        ASSESSMENT_AUTHORITY,
        SCOPE,
    )
    compatibility_fact = replace(
        compatibility_fact, digest=compatibility_fact.expected_digest()
    )
    constraint_fact = AssessedFact(
        ref("constraint_assessment", f"constraint.{impl['implementation_id']}"),
        constraint,
        "fixture.assessor",
        ASSESSMENT_AUTHORITY,
        SCOPE,
    )
    constraint_fact = replace(constraint_fact, digest=constraint_fact.expected_digest())
    return CandidateFacts(
        implementation=impl,
        conformance_claims=claims,
        compatibility=(compatibility_fact,),
        constraints=(constraint_fact,),
        risk_assessments=(ref("risk_assessment", f"risk.{impl['implementation_id']}"),),
    )


def candidate_resolver():
    return CandidateResolver(
        recognized_claim_issuers={"fixture.evaluator": {"authority.evaluation"}},
        recognized_assessment_issuers={
            "fixture.assessor": {"authority.assessment"}
        },
    )


class RequirementResolutionTests(unittest.TestCase):
    def setUp(self):
        self.resolver = RequirementResolver(
            resolver_id="core.requirement-resolver",
            recognized_requirement_issuers={
                "fixture.project": {"authority.requirements"},
                "fixture.override": {"authority.override"},
            },
        )

    def resolve(self, requirements, values=None):
        return self.resolver.resolve(
            requirements=requirements,
            validity_scope=SCOPE,
            condition_values=values or {},
            evaluated_at=NOW,
        )

    def test_resolution_is_deterministic_under_input_reordering(self):
        items = [requirement("requirement.required"), requirement("requirement.preferred", strength="preferred")]
        first = self.resolve(items)
        second = self.resolve(list(reversed(items)))

        self.assertEqual(first.record, second.record)
        self.assertEqual(
            [item["requirement_id"] for item in first.effective_requirements],
            ["requirement.preferred", "requirement.required"],
        )
        self.assertTrue(CapabilityContractValidator().validate(first.record).valid)

    def test_required_and_prohibited_conflict_remains_unresolved(self):
        result = self.resolve([
            requirement("requirement.required"),
            requirement("requirement.prohibited", strength="prohibited"),
        ])

        self.assertFalse(result.effective_requirements)
        self.assertEqual(result.unresolved[0]["reason_codes"], ["required_prohibited_conflict"])
        self.assertIn("HARD_REQUIREMENT_CONFLICT", {item.code for item in result.findings})

    def test_conflicting_required_versions_remain_unresolved(self):
        result = self.resolve([
            requirement("requirement.v1"),
            requirement("requirement.v2", version="2.0.0"),
        ])
        self.assertFalse(result.effective_requirements)
        self.assertIn("HARD_VERSION_CONFLICT", {item.code for item in result.findings})

    def test_prohibition_dominates_soft_preference(self):
        result = self.resolve([
            requirement("requirement.prohibited", strength="prohibited"),
            requirement("requirement.preferred", strength="preferred"),
        ])
        self.assertEqual([item["strength"] for item in result.effective_requirements], ["prohibited"])
        self.assertEqual([item["requirement_id"] for item in result.rejected_requirements], ["requirement.preferred"])

    def test_unrecognized_authority_fails_closed(self):
        result = self.resolve([requirement(authority=ref("authority_binding", "authority.forged"))])
        self.assertFalse(result.effective_requirements)
        self.assertIn("AUTHORITY_UNRECOGNIZED", {item.code for item in result.findings})

    def test_missing_condition_value_is_not_fabricated(self):
        condition = {"subject": ref("configuration", "mode"), "operator": "equals", "value": "release"}
        result = self.resolve([requirement(conditions=(condition,))])
        self.assertFalse(result.effective_requirements)
        self.assertIn("CONDITION_UNRESOLVED", {item.code for item in result.findings})

    def test_condition_can_be_satisfied_explicitly(self):
        condition = {"subject": ref("configuration", "mode"), "operator": "equals", "value": "release"}
        result = self.resolve(
            [requirement(conditions=(condition,))],
            {"configuration:mode:1.0.0": "release"},
        )
        self.assertEqual(len(result.effective_requirements), 1)

    def test_explicit_authorized_override_supersedes_prior(self):
        prior = requirement("requirement.prior")
        override = requirement(
            "requirement.override",
            issuer="fixture.override",
            authority=ref("authority_binding", "authority.override"),
            source_class="override",
            supersession=ref("capability_requirement", "requirement.prior"),
        )
        result = self.resolve([prior, override])
        self.assertEqual([item["requirement_id"] for item in result.effective_requirements], ["requirement.override"])
        self.assertIn("REQUIREMENT_SUPERSEDED", {item.code for item in result.findings})

    def test_ambiguous_supersession_blocks_all_involved_requirements(self):
        prior = requirement("requirement.prior")
        first = requirement(
            "requirement.override-a",
            supersession=ref("capability_requirement", "requirement.prior"),
        )
        second = requirement(
            "requirement.override-b",
            supersession=ref("capability_requirement", "requirement.prior"),
        )
        result = self.resolve([prior, first, second])
        self.assertFalse(result.effective_requirements)
        self.assertEqual(
            result.unresolved[0]["reason_codes"], ["supersession_ambiguous"]
        )


class CandidateAndBindingTests(unittest.TestCase):
    def setUp(self):
        self.requirement = requirement()
        self.capability = capability()
        self.requirement_resolution = RequirementResolver(
            resolver_id="core.requirement-resolver",
            recognized_requirement_issuers={"fixture.project": {"authority.requirements"}},
        ).resolve(
            requirements=[self.requirement],
            validity_scope=SCOPE,
            condition_values={},
            evaluated_at=NOW,
        )
        self.facts = candidate_facts()
        self.candidate_result = candidate_resolver().resolve(
            requirement=self.requirement,
            requirement_resolution=self.requirement_resolution,
            capability=self.capability,
            candidates=[self.facts],
            evaluated_at=NOW,
        )
        self.selection = {
            "schema": "capability-definition.v1",
            "entity_type": "selection_result",
            "selection_id": "selection.compiler",
            "requirement": ref("capability_requirement", "requirement.compile", issuer="fixture.project"),
            "eligible_candidates": list(self.candidate_result.eligible_candidates),
            "method": ref("resolution_method", "fixture.human-selection"),
            "evaluated_constraints": list(self.candidate_result.policy_input.constraint_assessments),
            "outcome": "selected",
            "selected_candidate": self.candidate_result.eligible_candidates[0],
            "rejected_candidates": [],
            "unresolved": [],
            "direct_inputs": [self.candidate_result.policy_input.requirement],
            "issuer": "fixture.selector",
            "limitations": [],
            "validity_scope": SCOPE,
            "supersession": None,
        }
        self.planner = BindingPlanner(
            issuer="core.binding-planner",
            authority_binding=BINDING_AUTHORITY,
            recognized_policy_issuers={"fixture.policy": {"authority.policy"}},
            recognized_claim_issuers={
                "fixture.evaluator": {"authority.evaluation"}
            },
            recognized_assessment_issuers={
                "fixture.assessor": {"authority.assessment"}
            },
        )

    def policy(self, outcome="ALLOW", **changes):
        issued_at = changes.pop("issued_at", NOW - timedelta(minutes=1))
        decision = PolicyDecisionFact(
            reference=ref("policy_decision", "policy.binding.compiler"),
            subject=ref("selection_result", "selection.compiler", issuer="fixture.selector"),
            outcome=outcome,
            supports=(ref("resolution_result", self.requirement_resolution.record["resolution_id"]),),
            issuer="fixture.policy",
            authority_binding=POLICY_AUTHORITY,
            validity_scope=SCOPE,
            issued_at=issued_at,
            **changes,
        )
        return replace(decision, digest=decision.expected_digest())

    def plan(self, policy=None, facts=None, selection=None):
        return self.planner.plan(
            binding_id="binding.compiler",
            requirement=self.requirement,
            capability=self.capability,
            selection_result=selection or self.selection,
            selected=facts or self.facts,
            policy_decision=policy or self.policy(),
            validity_scope=SCOPE,
            evaluated_at=NOW,
            risk_assessment=self.facts.risk_assessments[0],
        )

    def test_candidate_admission_preserves_facts_without_selecting(self):
        result = self.candidate_result
        self.assertEqual(len(result.eligible_candidates), 1)
        self.assertFalse(result.rejected_candidates)
        self.assertFalse(hasattr(result, "selected_candidate"))
        self.assertEqual(len(result.policy_input.compatibility_assessments), 1)

    def test_candidate_missing_dimension_fails_closed(self):
        facts = replace(self.facts, conformance_claims=self.facts.conformance_claims[:-1])
        result = candidate_resolver().resolve(
            requirement=self.requirement,
            requirement_resolution=self.requirement_resolution,
            capability=self.capability,
            candidates=[facts],
            evaluated_at=NOW,
        )
        self.assertFalse(result.eligible_candidates)
        self.assertIn("conformance_operational_ambiguous_or_missing", result.rejected_candidates[0]["reason_codes"])

    def test_incompatible_or_failed_constraint_rejects_candidate(self):
        for facts, expected in (
            (candidate_facts(compatibility="incompatible"), "compatibility_incompatible"),
            (candidate_facts(constraint="failed"), "constraint_failed"),
        ):
            result = candidate_resolver().resolve(
                requirement=self.requirement,
                requirement_resolution=self.requirement_resolution,
                capability=self.capability,
                candidates=[facts],
                evaluated_at=NOW,
            )
            self.assertIn(expected, result.rejected_candidates[0]["reason_codes"])

    def test_expired_compatibility_rejects_candidate_before_policy(self):
        expired = replace(
            self.facts.compatibility[0],
            valid_until=NOW - timedelta(seconds=1),
            digest="",
        )
        expired = replace(expired, digest=expired.expected_digest())
        facts = replace(
            self.facts,
            compatibility=(expired,),
        )
        result = candidate_resolver().resolve(
            requirement=self.requirement,
            requirement_resolution=self.requirement_resolution,
            capability=self.capability,
            candidates=[facts],
            evaluated_at=NOW,
        )
        self.assertIn(
            "compatibility_expired", result.rejected_candidates[0]["reason_codes"]
        )

    def test_untrusted_assessment_and_claim_authority_fail_closed(self):
        forged_fact = replace(self.facts.compatibility[0], digest="sha256:forged")
        forged_claim = dict(self.facts.conformance_claims[0])
        forged_claim["authority_binding"] = ref(
            "authority_binding", "authority.unrecognized"
        )
        facts = replace(
            self.facts,
            compatibility=(forged_fact,),
            conformance_claims=(forged_claim, *self.facts.conformance_claims[1:]),
        )
        result = candidate_resolver().resolve(
            requirement=self.requirement,
            requirement_resolution=self.requirement_resolution,
            capability=self.capability,
            candidates=[facts],
            evaluated_at=NOW,
        )
        reasons = result.rejected_candidates[0]["reason_codes"]
        self.assertIn("compatibility_fact_untrusted", reasons)
        self.assertIn("conformance_authority_unrecognized", reasons)

    def test_binding_plan_is_schema_valid_and_proposed_only(self):
        plan = self.plan()
        self.assertEqual(plan.binding["lifecycle_status"], "proposed")
        self.assertTrue(CapabilityContractValidator().validate(plan.binding).valid)
        self.assertIn(self.facts.compatibility[0].reference, plan.direct_supports)
        self.assertIn("did not evaluate or issue policy", plan.limitations[1])

    def test_non_allow_policy_cannot_bind(self):
        with self.assertRaisesRegex(BindingInputError, "cannot authorize"):
            self.plan(policy=self.policy("REVIEW_REQUIRED"))

    def test_forged_policy_digest_cannot_bind(self):
        with self.assertRaisesRegex(BindingInputError, "digest mismatch"):
            self.plan(policy=replace(self.policy(), digest="sha256:forged"))

    def test_future_expired_and_revoked_policy_fails_closed(self):
        invalid = (
            self.policy(issued_at=NOW + timedelta(minutes=1)),
            self.policy(valid_until=NOW - timedelta(seconds=1)),
            self.policy(revoked_at=NOW - timedelta(seconds=1)),
        )
        for decision in invalid:
            with self.assertRaises(BindingInputError):
                self.plan(policy=decision)

    def test_policy_must_bind_exact_selection(self):
        wrong = self.policy()
        wrong = replace(wrong, subject=ref("selection_result", "selection.other"), digest="")
        wrong = replace(wrong, digest=wrong.expected_digest())
        with self.assertRaisesRegex(BindingInputError, "exact selection"):
            self.plan(policy=wrong)

    def test_expired_conformance_cannot_bind(self):
        expired_claim = claim(
            self.facts.implementation,
            "operational",
            valid_until=NOW - timedelta(seconds=1),
        )
        facts = replace(
            self.facts,
            conformance_claims=(*self.facts.conformance_claims[:-1], expired_claim),
        )
        with self.assertRaisesRegex(BindingInputError, "expired"):
            self.plan(facts=facts)

    def test_binding_never_recovers_from_incompatible_fact(self):
        facts = replace(
            self.facts,
            compatibility=(replace(self.facts.compatibility[0], outcome="incompatible", digest=""),),
        )
        incompatible = facts.compatibility[0]
        facts = replace(
            facts,
            compatibility=(
                replace(incompatible, digest=incompatible.expected_digest()),
            ),
        )
        with self.assertRaisesRegex(BindingInputError, "not compatible"):
            self.plan(facts=facts)

    def test_binding_requires_compatibility_even_if_selection_exists(self):
        with self.assertRaisesRegex(BindingInputError, "compatibility assessment"):
            self.plan(facts=replace(self.facts, compatibility=()))

    def test_binding_rechecks_assessment_digest(self):
        forged = replace(self.facts.compatibility[0], digest="sha256:forged")
        with self.assertRaisesRegex(BindingInputError, "digest mismatch"):
            self.plan(facts=replace(self.facts, compatibility=(forged,)))

    def test_selection_mismatch_cannot_bind(self):
        other = implementation("implementation.other")
        selection = dict(self.selection)
        selection["selected_candidate"] = ref(
            "implementation", other["implementation_id"], digest=other["digest"], issuer=other["issuer"]
        )
        with self.assertRaises(ResolutionInputError):
            candidate_resolver().resolve(
                requirement=requirement(strength="prohibited"),
                requirement_resolution=self.requirement_resolution,
                capability=self.capability,
                candidates=[self.facts],
                evaluated_at=NOW,
            )
        with self.assertRaisesRegex(BindingInputError, "exact implementation"):
            self.plan(selection=selection)


if __name__ == "__main__":
    unittest.main()
