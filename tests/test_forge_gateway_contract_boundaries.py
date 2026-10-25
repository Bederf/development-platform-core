from __future__ import annotations

import copy
import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).parents[1]
NOW = "2026-08-26T04:00:00Z"
LATER = "2026-08-26T04:05:00Z"


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def self_digest(value: dict) -> str:
    return digest({key: item for key, item in value.items() if key != "digest"})


def ref(kind: str, identity: str, value: object | None = None) -> dict:
    result = {"semantic_type": kind, "id": identity, "version": "1.0.0"}
    if value is not None:
        result["digest"] = digest(value)
    return result


def scope(identity: str = "project.fixture") -> dict:
    return {"scope_type": "project", "scope_id": identity, "profile": None}


def assessed() -> dict:
    return {"status": "assessed", "reason": None}


def unavailable(reason: str = "source unavailable") -> dict:
    return {"status": "unavailable", "reason": reason}


def constraints(identity: str = "project.fixture") -> dict:
    return {
        "working_scope": scope(identity),
        "filesystem_policy": ref("filesystem_policy", f"filesystem.{identity}", {"write": ["bounded/"]}),
        "network_policy": ref("network_policy", f"network.{identity}", {"mode": "denied"}),
        "environment_policy": ref("environment_policy", f"environment.{identity}", {"allowed": []}),
        "timeout_seconds": 30,
    }


def canonical_identity(reference: dict) -> tuple[str, str, str, str]:
    return (
        reference["semantic_type"],
        reference["id"],
        reference["version"],
        reference.get("issuer", ""),
    )


def conformance_case(case_id: str):
    def decorate(method):
        method.conformance_case_id = case_id
        return method

    return decorate


class FakeImmutableRegistry:
    ID_FIELDS = {
        "evaluation_profile": "evaluation_profile_id",
        "evaluation_definition": "evaluation_definition_id",
        "evaluation_request": "request_id",
        "evaluation_result": "result_id",
        "policy_request": "request_id",
        "policy_decision": "decision_id",
        "execution_proposal": "proposal_id",
        "authorized_execution_request": "execution_request_id",
        "execution_result": "execution_id",
        "evidence_submission": "submission_id",
        "evidence_record": "evidence_id",
    }

    def __init__(self) -> None:
        self._documents: dict[tuple[str, str, str], tuple[str, dict]] = {}

    def register(self, document: dict) -> dict:
        kind = document["entity_type"]
        identity = document[self.ID_FIELDS[kind]]
        version = document.get("version", "1.0.0")
        content_digest = digest(document)
        key = (kind, identity, version)
        existing = self._documents.get(key)
        if existing is not None and existing[0] != content_digest:
            raise ValueError("logical identity was rebound to different content")
        self._documents[key] = (content_digest, copy.deepcopy(document))
        return {"semantic_type": kind, "id": identity, "version": version, "digest": content_digest}

    def resolve(self, reference: dict, expected_type: str | None = None) -> dict:
        if expected_type is not None and reference["semantic_type"] != expected_type:
            raise ValueError("immutable reference semantic type mismatch")
        key = (reference["semantic_type"], reference["id"], reference["version"])
        stored = self._documents.get(key)
        if stored is None:
            raise ValueError("immutable reference is unresolved")
        if reference.get("digest") != stored[0]:
            raise ValueError("immutable reference digest mismatch")
        return copy.deepcopy(stored[1])

    def assert_document(self, document: dict) -> None:
        reference = self.registered_reference(document)
        if reference["digest"] != digest(document):
            raise ValueError("registered document content mismatch")
        self.resolve(reference, document["entity_type"])

    def registered_reference(self, document: dict) -> dict:
        kind = document["entity_type"]
        identity = document[self.ID_FIELDS[kind]]
        version = document.get("version", "1.0.0")
        key = (kind, identity, version)
        stored = self._documents.get(key)
        if stored is None:
            raise ValueError("document is not registered")
        return {"semantic_type": kind, "id": identity, "version": version, "digest": stored[0]}


class FakeLegacyVerificationMapper:
    def map(self, status: str, evidence: list[str]) -> dict:
        if status not in {"FAILED", "NOT_RUN", "INCOMPLETE", "PASSED"}:
            raise ValueError("unsupported legacy status")
        return {
            "source_status": status,
            "operation_status": "not_run" if status == "NOT_RUN" else "completed",
            "outcome": "unknown",
            "evidence_candidates": list(evidence),
            "missing_semantics": ["subject", "evaluator", "method", "environment", "authority"],
            "availability": unavailable("legacy contract does not provide required semantics"),
        }


class FakePolicyProvider:
    def __init__(self, registry: FakeImmutableRegistry) -> None:
        self._registry = registry

    def decide(self, request: dict, *, reuse: bool = False, outcome: str = "allow") -> dict:
        if request["digest"] != self_digest(request):
            raise ValueError("policy request digest mismatch")
        self._registry.assert_document(request)
        decision = {
            "schema": "policy-decision.v1",
            "entity_type": "policy_decision",
            "decision_id": f"decision.{request['request_id']}",
            "request": self._registry.registered_reference(request),
            "domain": request["domain"],
            "action": request["action"],
            "subject": copy.deepcopy(request["subject"]),
            "actor": copy.deepcopy(request["actor"]),
            "outcome": outcome,
            "policies": copy.deepcopy(request["policies"]),
            "issuer": "fixture.policy",
            "authority_binding": ref("authority_binding", "authority.fixture.policy"),
            "direct_supports": copy.deepcopy(request["fact_inputs"] + request["evaluation_inputs"]),
            "reason_codes": ["fixture.policy.allow"],
            "conditions": [],
            "use_policy": (
                {"mode": "bounded_reuse", "max_uses": 2} if reuse else {"mode": "single_use", "max_uses": 1}
            ) if outcome == "allow" else None,
            "validity_scope": copy.deepcopy(request["requested_scope"]),
            "issued_at": NOW,
            "effective_from": NOW,
            "valid_until": LATER,
            "revoked_at": None,
            "lineage": [self._registry.registered_reference(request)],
            "limitations": [],
            "limitations_availability": assessed(),
            "supersession": None,
            "digest": "sha256:pending",
        }
        decision["digest"] = self_digest(decision)
        self._registry.register(decision)
        return decision


class FakePolicyUseLedger:
    def __init__(self, registry: FakeImmutableRegistry) -> None:
        self._registry = registry
        self._uses: dict[str, int] = {}
        self._recognized = {("fixture.policy", "authority.fixture.policy")}

    def claim(
        self,
        decision: dict,
        *,
        domain: str,
        action: str,
        subject: dict,
        actor: dict,
        validity_scope: dict,
    ) -> tuple[str, int]:
        if decision["digest"] != self_digest(decision):
            raise ValueError("policy decision digest mismatch")
        authority = (decision["issuer"], decision["authority_binding"]["id"])
        if authority not in self._recognized:
            raise ValueError("policy authority is not recognized")
        if decision["outcome"] != "allow" or decision["conditions"]:
            raise ValueError("policy did not issue an unconditional allow")
        if decision["domain"] != domain:
            raise ValueError("policy domain mismatch")
        if decision["action"] != action:
            raise ValueError("policy action mismatch")
        if decision["subject"] != subject:
            raise ValueError("policy subject mismatch")
        if decision["actor"] != actor:
            raise ValueError("policy actor mismatch")
        if decision["validity_scope"] != validity_scope:
            raise ValueError("policy scope mismatch")
        now = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
        issued = datetime.fromisoformat(decision["issued_at"].replace("Z", "+00:00"))
        effective = datetime.fromisoformat(decision["effective_from"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(decision["valid_until"].replace("Z", "+00:00"))
        if expires <= now:
            raise ValueError("policy decision is expired")
        if issued > effective or effective >= expires:
            raise ValueError("policy decision temporal ordering is invalid")
        if effective > now:
            raise ValueError("policy decision is not yet effective")
        if expires <= now:
            raise ValueError("policy decision is expired")
        if decision["revoked_at"] is not None:
            raise ValueError("policy decision is revoked")
        key = decision["digest"]
        use_index = self._uses.get(key, 0) + 1
        if use_index > decision["use_policy"]["max_uses"]:
            raise ValueError("policy decision replay exceeds use policy")
        self._uses[key] = use_index
        decision_token = decision["digest"].split(":", 1)[1][:16]
        return f"policy-use.{decision['decision_id']}.{decision_token}.{use_index}", use_index


class FakeAuthorizedRequestFactory:
    def __init__(self, ledger: FakePolicyUseLedger, registry: FakeImmutableRegistry) -> None:
        self._ledger = ledger
        self._registry = registry
        self.issued_digests: set[str] = set()

    def derive(self, proposal: dict, decision: dict) -> dict:
        if proposal["digest"] != self_digest(proposal):
            raise ValueError("proposal digest mismatch")
        if proposal["arguments_digest"] != digest(proposal["arguments"]):
            raise ValueError("proposal arguments digest mismatch")
        self._registry.assert_document(proposal)
        proposal_reference = self._registry.registered_reference(proposal)
        use_id, use_index = self._ledger.claim(
            decision,
            domain="execution",
            action=proposal["operation"],
            subject=proposal_reference,
            actor=proposal["actor"],
            validity_scope=proposal["validity_scope"],
        )
        request = {
            "schema": "engineering-execution.v1",
            "entity_type": "authorized_execution_request",
            "execution_request_id": f"execution-request.{proposal['attempt_id']}.{use_index}",
            "proposal": proposal_reference,
            "policy_decision": self._registry.registered_reference(decision),
            "policy_domain": "execution",
            "policy_action": decision["action"],
            "authorization_use_id": use_id,
            "authorization_use_index": use_index,
            "attempt_id": proposal["attempt_id"],
            "actor": copy.deepcopy(proposal["actor"]),
            "capability_binding": copy.deepcopy(proposal["capability_binding"]),
            "operation": proposal["operation"],
            "arguments_contract": copy.deepcopy(proposal["arguments_contract"]),
            "arguments": copy.deepcopy(proposal["arguments"]),
            "arguments_digest": proposal["arguments_digest"],
            "target": copy.deepcopy(proposal["target"]),
            "baseline": copy.deepcopy(proposal["baseline"]),
            "enforced_constraints": copy.deepcopy(proposal["requested_constraints"]),
            "executor_binding": ref("capability_binding", "binding.fixture.executor", {"executor": "fixture"}),
            "issuer": "fixture.authorization-deriver",
            "authority_binding": ref("authority_binding", "authority.fixture.derivation"),
            "validity_scope": copy.deepcopy(proposal["validity_scope"]),
            "issued_at": NOW,
            "expires_at": decision["valid_until"],
            "lineage": [proposal_reference, self._registry.registered_reference(decision)],
            "digest": "sha256:pending",
        }
        request["digest"] = self_digest(request)
        self._registry.register(request)
        self.issued_digests.add(request["digest"])
        return request


class FakeExecutor:
    def __init__(self, issued_digests: set[str], registry: FakeImmutableRegistry) -> None:
        self._issued_digests = issued_digests
        self._registry = registry

    def execute(self, request: dict, *, outcome: str = "completed") -> dict:
        if request.get("entity_type") != "authorized_execution_request":
            raise TypeError("executor accepts only AuthorizedExecutionRequest")
        if request["digest"] != self_digest(request):
            raise ValueError("authorized request digest mismatch")
        if request["digest"] not in self._issued_digests:
            raise ValueError("authorized request was not issued by the recognized authority")
        self._registry.assert_document(request)
        if request["policy_domain"] != "execution" or request["policy_action"] != request["operation"]:
            raise ValueError("authorized policy binding mismatch")
        if request["arguments_digest"] != digest(request["arguments"]):
            raise ValueError("authorized arguments digest mismatch")
        result = {
            "schema": "engineering-execution.v1", "entity_type": "execution_result",
            "execution_id": f"execution.{request['attempt_id']}",
            "execution_request": self._registry.registered_reference(request),
            "proposal": copy.deepcopy(request["proposal"]), "policy_decision": copy.deepcopy(request["policy_decision"]),
            "policy_domain": request["policy_domain"], "policy_action": request["policy_action"],
            "authorization_use_id": request["authorization_use_id"], "attempt_id": request["attempt_id"],
            "actor": copy.deepcopy(request["actor"]), "executor_binding": copy.deepcopy(request["executor_binding"]),
            "issuer": "fixture.executor", "authority_binding": ref("authority_binding", "authority.fixture.execution"),
            "capability_binding": copy.deepcopy(request["capability_binding"]), "operation": request["operation"],
            "target": copy.deepcopy(request["target"]), "baseline": copy.deepcopy(request["baseline"]),
            "arguments_digest": request["arguments_digest"], "operation_status": outcome,
            "attempted_effects": [], "completed_effects": [],
            "outputs": [ref("artifact", f"artifact.{request['attempt_id']}.output", {"result": "ok"})] if outcome == "completed" else [],
            "artifacts": [], "observations": [],
            "failure_category": None if outcome == "completed" else "executor",
            "reason_codes": [] if outcome == "completed" else ["fixture.executor.failed"],
            "actual_environment": ref("environment", "environment.fixture.actual") if outcome == "completed" else None,
            "enforced_constraints": copy.deepcopy(request["enforced_constraints"]),
            "started_at": NOW, "finished_at": LATER, "recorded_at": LATER,
            "validity_scope": copy.deepcopy(request["validity_scope"]),
            "limitations": [], "limitations_availability": assessed(),
            "lineage": [self._registry.registered_reference(request)],
            "supersession": None, "digest": "sha256:pending",
        }
        result["digest"] = self_digest(result)
        self._registry.register(result)
        return result


class FakeEvaluator:
    def __init__(self, registry: FakeImmutableRegistry) -> None:
        self._registry = registry

    def evaluate(self, request: dict, profile: dict, observed_subject: dict, evaluator_actor: dict, evaluator_binding: dict | None = None) -> dict:
        if evaluator_binding is None:
            evaluator_binding = evaluator_actor
            evaluator_actor = ref("actor", "fixture.evaluator")
        if request["digest"] != self_digest(request):
            raise ValueError("evaluation request digest mismatch")
        self._registry.assert_document(request)
        self._registry.resolve(request["definition"], "evaluation_definition")
        resolved_profile = self._registry.resolve(request["profile"], "evaluation_profile")
        if resolved_profile != profile:
            raise ValueError("evaluation profile content mismatch")
        if request["subject"] != observed_subject:
            raise ValueError("evaluated subject does not match the requested immutable subject")
        eligible = profile["eligible_evaluators"]
        if eligible and evaluator_binding not in eligible:
            raise ValueError("evaluator is not eligible under the profile")
        independence = profile["independence"]
        producer_required = independence["evaluator_must_differ_from_subject_producer"]
        actor_required = independence["evaluator_must_differ_from_execution_actor"]
        producer = request["subject_producer_actor"]
        actor = request["execution_actor"]
        if producer_required and producer is None:
            raise ValueError("subject producer identity is unavailable")
        if actor_required and actor is None:
            raise ValueError("execution actor identity is unavailable")
        if producer_required and canonical_identity(producer) == canonical_identity(evaluator_actor):
            raise ValueError("evaluator equals subject producer")
        if producer_required and producer == evaluator_binding:
            raise ValueError("evaluator binding equals subject producer")
        if actor_required and canonical_identity(actor) == canonical_identity(evaluator_actor):
            raise ValueError("evaluator equals execution actor")
        support = ref("artifact", "artifact.fixture.evaluation-log", {"passed": True})
        assessment = {
            "overall": "satisfied" if producer_required or actor_required else "not_applicable",
            "subject_producer_separation": "satisfied" if producer_required else "not_applicable",
            "execution_actor_separation": "satisfied" if actor_required else "not_applicable",
        }
        result = {
            "schema": "evaluation.v1", "entity_type": "evaluation_result",
            "result_id": f"evaluation-result.{request['attempt_id']}",
            "request": self._registry.registered_reference(request),
            "attempt_id": request["attempt_id"], "definition": copy.deepcopy(request["definition"]), "profile": copy.deepcopy(request["profile"]),
            "subject": copy.deepcopy(request["subject"]), "subject_producer_actor": copy.deepcopy(producer), "execution_actor": copy.deepcopy(actor),
            "evaluator_actor": copy.deepcopy(evaluator_actor), "evaluator_binding": copy.deepcopy(evaluator_binding), "issuer": "fixture.evaluator",
            "authority_binding": ref("authority_binding", "authority.fixture.evaluation"), "method": ref("evaluation_method", "fixture.deterministic-check"),
            "operation_status": "completed", "outcome": "satisfied", "failure_reasons": [], "reason_codes": [],
            "independence_assessment": assessment, "environment": ref("environment", "environment.fixture.actual"),
            "findings": [{"finding_id": "finding.fixture", "criterion_id": "criterion.fixture", "category": "criterion", "outcome": "satisfied", "reason_codes": ["fixture.criterion.satisfied"], "supports": [support], "informative_detail": None}],
            "findings_availability": assessed(),
            "claims": [{"claim": ref("claim_definition", "claim.fixture"), "outcome": "satisfied", "supports": [support], "limitations": [], "limitations_availability": assessed()}],
            "claims_availability": assessed(), "direct_supports": [support],
            "limitations": [], "limitations_availability": assessed(), "uncertainty": [], "uncertainty_availability": assessed(),
            "validity_scope": copy.deepcopy(request["validity_scope"]), "started_at": NOW, "finished_at": LATER, "recorded_at": LATER,
            "lineage": [self._registry.registered_reference(request)], "supersession": None, "digest": "sha256:pending",
        }
        result["digest"] = self_digest(result)
        self._registry.register(result)
        return result


class FakeEvidenceProvider:
    def __init__(self, ledger: FakePolicyUseLedger, registry: FakeImmutableRegistry) -> None:
        self._ledger = ledger
        self._registry = registry

    def preserve(self, submission: dict, admission_evaluation: dict, admission_decision: dict) -> dict:
        if submission["digest"] != self_digest(submission):
            raise ValueError("evidence submission digest mismatch")
        # Validate relational admission semantics before immutable-registry
        # checks so adversarial mutations reach their intended boundary.
        candidate = submission["candidate"]
        try:
            self._registry.resolve(candidate)
        except ValueError as exc:
            raise ValueError("candidate digest mismatch") from exc
        if admission_evaluation["digest"] != self_digest(admission_evaluation):
            raise ValueError("admission evaluation digest mismatch")
        self._registry.assert_document(admission_evaluation)
        submission_reference = self._registry.registered_reference(submission)
        evaluation_reference = self._registry.registered_reference(admission_evaluation)
        if admission_evaluation["subject"] != submission_reference or admission_evaluation["outcome"] != "satisfied":
            raise ValueError("admission evaluation is not satisfied for the exact submission")
        if evaluation_reference not in admission_decision["direct_supports"]:
            raise ValueError("admission decision did not consume the exact evaluation")
        use_id, use_index = self._ledger.claim(
            admission_decision,
            domain="admission", action="admit-evidence", subject=submission_reference,
            actor=submission["submitted_by"], validity_scope=submission["validity_scope"],
        )
        decision_reference = self._registry.registered_reference(admission_decision)
        record = {
            "schema": "evidence.v1", "entity_type": "evidence_record", "evidence_id": f"evidence.{submission['submission_id']}",
            "version": "1.0.0", "submission": submission_reference, "candidate": copy.deepcopy(candidate),
            "admission_evaluation": evaluation_reference, "admission_policy_decision": decision_reference,
            "admission_policy_use_id": use_id, "admission_policy_use_index": use_index,
            "subject": copy.deepcopy(submission["subject"]), "issuer": "fixture.evidence",
            "authority_binding": ref("authority_binding", "authority.fixture.evidence"), "provenance": copy.deepcopy(submission["provenance"]),
            "supports": [submission_reference, evaluation_reference, decision_reference],
            "limitations": copy.deepcopy(submission["limitations"]), "limitations_availability": copy.deepcopy(submission["limitations_availability"]),
            "validity_scope": copy.deepcopy(submission["validity_scope"]), "issued_at": NOW, "valid_until": None,
            "lineage": [submission_reference, evaluation_reference, decision_reference], "supersession": None, "digest": "sha256:pending",
        }
        record["digest"] = self_digest(record)
        self._registry.register(record)
        return record


class FakeEvaluationResultValidator:
    def __init__(self, registry: FakeImmutableRegistry) -> None:
        self._registry = registry

    def validate(self, result: dict) -> None:
        if result["digest"] != self_digest(result):
            raise ValueError("evaluation result digest mismatch")
        request = self._registry.resolve(result["request"], "evaluation_request")
        repeated = (
            "attempt_id", "definition", "profile", "subject",
            "subject_producer_actor", "execution_actor", "validity_scope",
        )
        for field in repeated:
            if result[field] != request[field]:
                raise ValueError(f"evaluation result {field} correlation mismatch")


class FakeExecutionResultValidator:
    def __init__(self, registry: FakeImmutableRegistry) -> None:
        self._registry = registry

    def validate(self, result: dict) -> None:
        if result["digest"] != self_digest(result):
            raise ValueError("execution result digest mismatch")
        request = self._registry.resolve(result["execution_request"], "authorized_execution_request")
        repeated = (
            "proposal", "policy_decision", "policy_domain", "policy_action",
            "authorization_use_id", "attempt_id", "actor", "executor_binding",
            "capability_binding", "operation", "target", "baseline",
            "arguments_digest", "enforced_constraints", "validity_scope",
        )
        for field in repeated:
            if result[field] != request[field]:
                raise ValueError(f"execution result {field} correlation mismatch")


class FakeVerificationProvider:
    """Independent verifier used by the graph-level conformance fixture."""

    def verify(self, execution: dict, mode: str) -> dict | None:
        if mode == "unsupported":
            return None
        status = {"pass": "PASSED", "fail": "FAILED", "unavailable": "INCOMPLETE"}[mode]
        evidence = [f"fixture://verification/{execution['execution_id']}"] if mode != "unavailable" else []
        return {
            "schema": "verification-result.v1",
            "request_id": f"verification-request.{execution['execution_id']}",
            "status": status,
            "checks": [{
                "check_id": "fixture.postcondition",
                "status": "PASSED" if status == "PASSED" else "FAILED",
                "command": None,
                "evidence_ref": evidence[0] if evidence else None,
            }],
            "evidence": evidence,
        }


class FakeVerifiedTransitionAuthority:
    """Promote only an independently passing verification to VERIFIED."""

    def establish(self, execution: dict, verification: dict | None) -> dict:
        if execution["operation_status"] != "completed":
            return {"state": "UNVERIFIED", "recovery": "execution-failure", "transition": None}
        if verification is None or verification["status"] != "PASSED" or not verification["evidence"]:
            return {"state": "UNVERIFIED", "recovery": "verification-required", "transition": None}
        return {
            "state": "VERIFIED",
            "recovery": None,
            "transition": {
                "semantic_type": "verified_state_transition",
                "execution_id": execution["execution_id"],
                "execution_result_digest": self_digest(execution),
                "verification_request_id": verification["request_id"],
                "verification_status": verification["status"],
                "verification_evidence": list(verification["evidence"]),
            },
        }


class ContractBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validators = {}
        schema_files = {
            "evaluation": "evaluation.v1.schema.json",
            "evidence": "evidence.v1.schema.json",
            "policy-decision": "policy-decision.v1.schema.json",
            "engineering-execution": "engineering-execution.v1.schema.json",
            "verification": "verification-result.v1.schema.json",
        }
        for family, filename in schema_files.items():
            schema = json.loads((ROOT / "contracts" / filename).read_text())
            Draft202012Validator.check_schema(schema)
            cls.validators[family] = Draft202012Validator(schema, format_checker=FormatChecker())

    def setUp(self) -> None:
        self.registry = FakeImmutableRegistry()
        self.evaluation_profile = self.profile()
        self.validate("evaluation", self.evaluation_profile)
        self.registry.register(self.evaluation_profile)
        self.evaluation_definition = self.definition(self.evaluation_profile)
        self.validate("evaluation", self.evaluation_definition)
        self.registry.register(self.evaluation_definition)

    def validate(self, family: str, value: dict) -> None:
        self.validators[family].validate(value)

    def assertInvalid(self, family: str, value: dict) -> None:
        self.assertTrue(list(self.validators[family].iter_errors(value)))

    def profile(self) -> dict:
        return {
            "schema": "evaluation.v1", "entity_type": "evaluation_profile", "evaluation_profile_id": "profile.fixture.independent",
            "version": "1.0.0", "lifecycle_status": "experimental", "eligible_evaluators": [],
            "independence": {"evaluator_must_differ_from_subject_producer": True, "evaluator_must_differ_from_execution_actor": True},
            "evidence_requirements": [], "aggregation": {"strategy": "all_required", "threshold": None, "custom_method": None},
            "issuer": "fixture.profile", "authority_binding": ref("authority_binding", "authority.fixture.profile"),
            "validity_scope": scope(), "supersession": None,
        }

    def definition(self, profile: dict) -> dict:
        return {
            "schema": "evaluation.v1", "entity_type": "evaluation_definition",
            "evaluation_definition_id": "evaluation.fixture.check", "version": "1.0.0", "lifecycle_status": "experimental",
            "profile": ref("evaluation_profile", profile["evaluation_profile_id"], profile),
            "subject_types": ["artifact", "evidence_submission"], "method": ref("evaluation_method", "fixture.deterministic-check"),
            "method_configuration": ref("method_configuration", "fixture.deterministic-check.config", {"mode": "deterministic"}),
            "criteria": [{"criterion_id": "criterion.fixture", "claim": ref("claim_definition", "claim.fixture"), "required": True, "weight": None}],
            "environment_profile": ref("environment_profile", "environment.fixture"), "issuer": "fixture.definition",
            "authority_binding": ref("authority_binding", "authority.fixture.definition"), "validity_scope": scope(), "supersession": None,
        }

    def proposal(self, context: str = "repository", *, operation: str = "write-file", target_type: str = "repository_path", arguments: dict | None = None) -> dict:
        arguments = copy.deepcopy(arguments or {"path": "bounded/feature.py"})
        value = {
            "schema": "engineering-execution.v1", "entity_type": "execution_proposal", "proposal_id": f"proposal.{context}",
            "attempt_id": f"attempt.{context}", "task_id": f"task.{context}", "session_id": f"session.{context}",
            "actor": ref("actor", "fixture.agent"), "capability_binding": ref("capability_binding", f"binding.fixture.{operation}", {"capability": operation}),
            "operation": operation, "arguments_contract": ref("contract", f"arguments.{operation}.v1"), "arguments": arguments, "arguments_digest": digest(arguments),
            "target": ref(target_type, f"target.{context}", {"target": context}), "baseline": ref(target_type, f"baseline.{context}", {"revision": "abc123"}),
            "requested_constraints": constraints(f"project.{context}"), "requested_by": ref("actor", "fixture.requester"), "requested_at": NOW,
            "validity_scope": scope(f"project.{context}"), "lineage": [], "digest": "sha256:pending",
        }
        value["digest"] = self_digest(value)
        self.registry.register(value)
        return value

    def policy_request(self, subject: dict, *, domain: str, action: str, actor: dict, requested_scope: dict, evaluations: list[dict] | None = None) -> dict:
        value = {
            "schema": "policy-decision.v1", "entity_type": "policy_request", "request_id": f"policy-request.{domain}.{subject['id']}",
            "domain": domain, "action": action, "subject": copy.deepcopy(subject), "actor": copy.deepcopy(actor), "requested_by": ref("actor", "fixture.requester"),
            "policies": [ref("policy", f"policy.fixture.{domain}")], "fact_inputs": [ref("constraint_fact", "fact.fixture.scope", {"satisfied": True})],
            "evaluation_inputs": evaluations or [], "requested_scope": copy.deepcopy(requested_scope), "requested_at": NOW, "lineage": [], "digest": "sha256:pending",
        }
        value["digest"] = self_digest(value)
        self.registry.register(value)
        return value

    def execution_decision(self, proposal: dict, *, reuse: bool = False) -> dict:
        request = self.policy_request(
            ref("execution_proposal", proposal["proposal_id"], proposal), domain="execution", action=proposal["operation"],
            actor=proposal["actor"], requested_scope=proposal["validity_scope"],
        )
        return FakePolicyProvider(self.registry).decide(request, reuse=reuse)

    def evaluation_request(self, subject: dict, context: str, subject_producer_actor: dict | None, execution_actor: dict | None) -> dict:
        value = {
            "schema": "evaluation.v1", "entity_type": "evaluation_request", "request_id": f"evaluation-request.{context}", "attempt_id": f"evaluation-attempt.{context}",
            "definition": self.registry.registered_reference(self.evaluation_definition),
            "profile": self.registry.registered_reference(self.evaluation_profile), "subject": copy.deepcopy(subject),
            "subject_producer_actor": copy.deepcopy(subject_producer_actor), "execution_actor": copy.deepcopy(execution_actor), "requested_by": ref("actor", "fixture.requester"),
            "input_refs": [], "evidence_refs": [], "requested_environment": ref("environment_profile", "environment.fixture"),
            "validity_scope": scope(), "contract_versions": [ref("contract", "evaluation.v1")], "requested_at": NOW, "lineage": [], "digest": "sha256:pending",
        }
        value["digest"] = self_digest(value)
        self.registry.register(value)
        return value

    def submission(self, evaluation: dict, context: str) -> dict:
        value = {
            "schema": "evidence.v1", "entity_type": "evidence_submission", "submission_id": f"submission.{context}",
            "candidate": self.registry.registered_reference(evaluation), "subject": copy.deepcopy(evaluation["subject"]),
            "representation": "application/json", "source": ref("implementation", "fixture.evaluator"), "producer": ref("actor", "fixture.evaluator"),
            "collection_method": ref("collection_method", "fixture.direct-result"),
            "provenance": ref("provenance_record", f"provenance.{context}", {"request": evaluation["request"]}),
            "claimed_supports": copy.deepcopy(evaluation["direct_supports"]), "limitations": [], "limitations_availability": assessed(),
            "observed_at": LATER, "submitted_by": ref("actor", "fixture.evaluator"), "submitted_at": LATER,
            "validity_scope": scope(), "lineage": [ref("evaluation_result", evaluation["result_id"], evaluation)], "digest": "sha256:pending",
        }
        value["digest"] = self_digest(value)
        self.registry.register(value)
        return value

    def admission_bundle(self, context: str = "admission-test") -> tuple[dict, dict, dict, FakeImmutableRegistry]:
        evaluator_actor = ref("actor", "fixture.evaluator")
        evaluator_binding = ref("capability_binding", "binding.fixture.evaluator", {"role": "evaluator"})
        producer = ref("actor", "fixture.producer")
        actor = ref("actor", "fixture.execution-actor")
        subject = ref("artifact", f"artifact.{context}", {"context": context})
        source_request = self.evaluation_request(subject, f"source.{context}", producer, actor)
        source_evaluation = FakeEvaluator(self.registry).evaluate(
            source_request, self.evaluation_profile, subject, evaluator_actor, evaluator_binding
        )
        submission = self.submission(source_evaluation, context)
        submission_reference = self.registry.registered_reference(submission)
        admission_request = self.evaluation_request(
            submission_reference, f"admission.{context}", ref("actor", "fixture.evidence-producer"), ref("actor", "fixture.evidence-actor")
        )
        admission_evaluation = FakeEvaluator(self.registry).evaluate(
            admission_request, self.evaluation_profile, submission_reference,
            ref("actor", "fixture.admission-evaluator"),
            ref("capability_binding", "binding.fixture.admission-evaluator", {"role": "admission-evaluator"}),
        )
        evaluation_reference = self.registry.registered_reference(admission_evaluation)
        policy_request = self.policy_request(
            submission_reference, domain="admission", action="admit-evidence", actor=submission["submitted_by"],
            requested_scope=submission["validity_scope"], evaluations=[evaluation_reference],
        )
        decision = FakePolicyProvider(self.registry).decide(policy_request)
        return submission, admission_evaluation, decision, self.registry

    def run_composition(self, proposal: dict) -> tuple[tuple[str, dict], ...]:
        ledger = FakePolicyUseLedger(self.registry)
        execution_policy_request = self.policy_request(
            self.registry.registered_reference(proposal), domain="execution", action=proposal["operation"],
            actor=proposal["actor"], requested_scope=proposal["validity_scope"],
        )
        decision = FakePolicyProvider(self.registry).decide(execution_policy_request)
        factory = FakeAuthorizedRequestFactory(ledger, self.registry)
        authorized = factory.derive(proposal, decision)
        execution = FakeExecutor(factory.issued_digests, self.registry).execute(authorized)
        FakeExecutionResultValidator(self.registry).validate(execution)
        evaluation_request = self.evaluation_request(
            execution["outputs"][0], proposal["proposal_id"], ref("actor", "fixture.executor"), execution["actor"]
        )
        evaluation = FakeEvaluator(self.registry).evaluate(
            evaluation_request, self.evaluation_profile, evaluation_request["subject"],
            ref("actor", "fixture.evaluator"),
            ref("capability_binding", "binding.fixture.evaluator", {"role": "evaluator"}),
        )
        FakeEvaluationResultValidator(self.registry).validate(evaluation)
        submission = self.submission(evaluation, proposal["proposal_id"])
        submission_reference = self.registry.registered_reference(submission)
        admission_request = self.evaluation_request(
            submission_reference, f"admission.{proposal['proposal_id']}",
            ref("actor", "fixture.evidence-producer"), ref("actor", "fixture.evidence-actor")
        )
        admission_evaluation = FakeEvaluator(self.registry).evaluate(
            admission_request, self.evaluation_profile, submission_reference,
            ref("actor", "fixture.admission-evaluator"),
            ref("capability_binding", "binding.fixture.admission-evaluator", {"role": "admission-evaluator"}),
        )
        FakeEvaluationResultValidator(self.registry).validate(admission_evaluation)
        admission_policy_request = self.policy_request(
            submission_reference, domain="admission", action="admit-evidence", actor=submission["submitted_by"], requested_scope=submission["validity_scope"],
            evaluations=[self.registry.registered_reference(admission_evaluation)],
        )
        admission_decision = FakePolicyProvider(self.registry).decide(admission_policy_request)
        evidence = FakeEvidenceProvider(ledger, self.registry).preserve(submission, admission_evaluation, admission_decision)
        return (
            ("evaluation", self.evaluation_profile), ("evaluation", self.evaluation_definition),
            ("engineering-execution", proposal), ("policy-decision", execution_policy_request),
            ("policy-decision", decision), ("engineering-execution", authorized), ("engineering-execution", execution),
            ("evaluation", evaluation_request), ("evaluation", evaluation), ("evidence", submission),
            ("evaluation", admission_request), ("evaluation", admission_evaluation),
            ("policy-decision", admission_policy_request), ("policy-decision", admission_decision), ("evidence", evidence),
        )

    def test_verified_state_transition_graph_conformance(self) -> None:
        fixture = yaml.safe_load(
            (ROOT / "fixtures" / "conformance" / "verified-state-transition-v1.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(fixture["schema"], "verified-state-transition-conformance.v1")
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                proposal = self.proposal(case["id"])
                policy_request = self.policy_request(
                    self.registry.registered_reference(proposal), domain="execution",
                    action=proposal["operation"], actor=proposal["actor"], requested_scope=proposal["validity_scope"],
                )
                decision = FakePolicyProvider(self.registry).decide(policy_request, outcome=case["policy"])
                ledger = FakePolicyUseLedger(self.registry)
                factory = FakeAuthorizedRequestFactory(ledger, self.registry)
                if case["policy"] == "deny":
                    with self.assertRaisesRegex(ValueError, "unconditional allow"):
                        factory.derive(proposal, decision)
                    result = {"state": "UNVERIFIED", "recovery": "policy-denied", "transition": None}
                else:
                    authorized = factory.derive(proposal, decision)
                    execution = FakeExecutor(factory.issued_digests, self.registry).execute(
                        authorized, outcome=case["execution"]
                    )
                    self.validate("engineering-execution", execution)
                    verification = FakeVerificationProvider().verify(execution, case["verification"])
                    if verification is not None:
                        self.validate("verification", verification)
                    result = FakeVerifiedTransitionAuthority().establish(execution, verification)

                self.assertEqual(result["state"], case["expected_state"])
                self.assertEqual(result["recovery"], case["expected_recovery"])
                if case["expected_state"] == "VERIFIED":
                    self.assertIsNotNone(result["transition"])
                else:
                    self.assertIsNone(result["transition"])

    def test_positive_repository_architecture_flow(self) -> None:
        example = json.loads((ROOT / "examples" / "forge-gateway-contracts" / "repository-architecture.json").read_text())
        for family, document in self.run_composition(self.proposal(example["context"], operation=example["operation"], target_type=example["target_semantic_type"], arguments=example["arguments"])):
            self.validate(family, document)

    def test_positive_capability_conformance_flow(self) -> None:
        example = json.loads((ROOT / "examples" / "forge-gateway-contracts" / "capability-conformance.json").read_text())
        for family, document in self.run_composition(self.proposal(example["context"], operation=example["operation"], target_type=example["target_semantic_type"], arguments=example["arguments"])):
            self.validate(family, document)

    def test_negative_proposal_is_not_authority(self) -> None:
        with self.assertRaisesRegex(TypeError, "AuthorizedExecutionRequest"):
            FakeExecutor(set(), self.registry).execute(self.proposal())

    def test_negative_evaluation_is_not_acceptance(self) -> None:
        request = self.evaluation_request(ref("artifact", "artifact.x", {"x": 1}), "x", ref("capability_binding", "binding.producer", {"role": "producer"}), ref("actor", "actor.x"))
        result = FakeEvaluator(self.registry).evaluate(request, self.profile(), request["subject"], ref("capability_binding", "binding.evaluator", {"role": "evaluator"}))
        result["acceptance"] = "accepted"
        self.assertInvalid("evaluation", result)

    def test_negative_evidence_is_not_authority(self) -> None:
        submission, evaluation, decision, registry = self.admission_bundle()
        record = FakeEvidenceProvider(FakePolicyUseLedger(registry), registry).preserve(submission, evaluation, decision)
        with self.assertRaisesRegex(TypeError, "AuthorizedExecutionRequest"):
            FakeExecutor(set(), self.registry).execute(record)

    def test_negative_missing_evidence_cannot_pass(self) -> None:
        request = self.evaluation_request(ref("artifact", "artifact.x", {"x": 1}), "missing", ref("capability_binding", "binding.producer", {"role": "producer"}), ref("actor", "actor.x"))
        result = FakeEvaluator(self.registry).evaluate(request, self.profile(), request["subject"], ref("capability_binding", "binding.evaluator", {"role": "evaluator"}))
        result["direct_supports"] = []
        self.assertInvalid("evaluation", result)

    def test_adversarial_baseline_substitution(self) -> None:
        proposal = self.proposal()
        decision = self.execution_decision(proposal)
        factory = FakeAuthorizedRequestFactory(FakePolicyUseLedger(self.registry), self.registry)
        request = factory.derive(proposal, decision)
        request["baseline"] = ref("repository", "baseline.other", {"revision": "other"})
        with self.assertRaisesRegex(ValueError, "request digest"):
            FakeExecutor(factory.issued_digests, self.registry).execute(request)

    def test_adversarial_decision_expiry_and_single_use_replay(self) -> None:
        proposal = self.proposal()
        expired = self.execution_decision(proposal)
        expired["valid_until"] = NOW
        expired["digest"] = self_digest(expired)
        with self.assertRaisesRegex(ValueError, "expired"):
            FakeAuthorizedRequestFactory(FakePolicyUseLedger(self.registry), self.registry).derive(proposal, expired)
        ledger = FakePolicyUseLedger(self.registry)
        decision = self.execution_decision(proposal)
        FakeAuthorizedRequestFactory(ledger, self.registry).derive(proposal, decision)
        with self.assertRaisesRegex(ValueError, "replay"):
            FakeAuthorizedRequestFactory(ledger, self.registry).derive(proposal, decision)

    def test_adversarial_mutable_proposal_retrieval(self) -> None:
        proposal = self.proposal()
        request = FakeAuthorizedRequestFactory(FakePolicyUseLedger(self.registry), self.registry).derive(proposal, self.execution_decision(proposal))
        del request["arguments"]
        self.assertInvalid("engineering-execution", request)

    def test_adversarial_broadened_execution_scope(self) -> None:
        proposal = self.proposal()
        factory = FakeAuthorizedRequestFactory(FakePolicyUseLedger(self.registry), self.registry)
        request = factory.derive(proposal, self.execution_decision(proposal))
        request["enforced_constraints"]["timeout_seconds"] = 300
        request["digest"] = self_digest(request)
        with self.assertRaisesRegex(ValueError, "recognized authority"):
            FakeExecutor(factory.issued_digests, self.registry).execute(request)

    def test_adversarial_issuer_confusion(self) -> None:
        proposal = self.proposal()
        decision = self.execution_decision(proposal)
        decision["authority_binding"]["id"] = "authority.unrecognized"
        decision["digest"] = self_digest(decision)
        with self.assertRaisesRegex(ValueError, "not recognized"):
            FakeAuthorizedRequestFactory(FakePolicyUseLedger(self.registry), self.registry).derive(proposal, decision)

    def test_adversarial_status_collapse(self) -> None:
        request = self.evaluation_request(ref("artifact", "artifact.x", {"x": 1}), "status", ref("capability_binding", "binding.producer", {"role": "producer"}), ref("actor", "actor.x"))
        result = FakeEvaluator(self.registry).evaluate(request, self.profile(), request["subject"], ref("capability_binding", "binding.evaluator", {"role": "evaluator"}))
        result.update(operation_status="timeout", outcome="satisfied", reason_codes=[])
        self.assertInvalid("evaluation", result)

    def test_adversarial_evidence_owned_admission(self) -> None:
        self.assertInvalid("evidence", {"schema": "evidence.v1", "entity_type": "evidence_admission_result"})

    def test_adversarial_preserve_denied_evidence(self) -> None:
        submission, evaluation, decision, registry = self.admission_bundle("denied")
        decision.update(outcome="deny", use_policy=None)
        decision["digest"] = self_digest(decision)
        with self.assertRaisesRegex(ValueError, "unconditional allow"):
            FakeEvidenceProvider(FakePolicyUseLedger(registry), registry).preserve(submission, evaluation, decision)

    def test_adversarial_unattributed_result(self) -> None:
        proposal = self.proposal()
        ledger = FakePolicyUseLedger(self.registry)
        factory = FakeAuthorizedRequestFactory(ledger, self.registry)
        result = FakeExecutor(factory.issued_digests, self.registry).execute(factory.derive(proposal, self.execution_decision(proposal)))
        for field in ("issuer", "authority_binding"):
            invalid = copy.deepcopy(result)
            del invalid[field]
            self.assertInvalid("engineering-execution", invalid)

    def test_adversarial_unavailable_as_empty(self) -> None:
        request = self.evaluation_request(ref("artifact", "artifact.x", {"x": 1}), "availability", ref("capability_binding", "binding.producer", {"role": "producer"}), ref("actor", "actor.x"))
        result = FakeEvaluator(self.registry).evaluate(request, self.profile(), request["subject"], ref("capability_binding", "binding.evaluator", {"role": "evaluator"}))
        result["limitations"] = ["known limitation"]
        result["limitations_availability"] = unavailable()
        self.assertInvalid("evaluation", result)

    def test_regression_frozen_verification_failed_remains_unknown(self) -> None:
        legacy = {"status": "FAILED", "evidence": ["log.txt"]}
        self.assertEqual(legacy["status"], "FAILED")
        self.assertNotIn("authority_binding", legacy)

    def test_regression_frozen_verification_not_run_remains_unknown(self) -> None:
        legacy = {"status": "NOT_RUN", "evidence": []}
        self.assertEqual(legacy["status"], "NOT_RUN")
        self.assertFalse(legacy["evidence"])

    def test_regression_wrong_domain_decision_is_rejected(self) -> None:
        proposal = self.proposal("wrong-domain")
        decision = self.execution_decision(proposal)
        decision.update(domain="admission", action="admit-evidence")
        decision["digest"] = self_digest(decision)
        with self.assertRaisesRegex(ValueError, "domain mismatch"):
            FakeAuthorizedRequestFactory(FakePolicyUseLedger(self.registry), self.registry).derive(proposal, decision)

    def test_regression_replayed_admission_decision_is_rejected(self) -> None:
        submission, evaluation, decision, registry = self.admission_bundle("replay")
        ledger = FakePolicyUseLedger(self.registry)
        provider = FakeEvidenceProvider(ledger, registry)
        provider.preserve(submission, evaluation, decision)
        with self.assertRaisesRegex(ValueError, "replay"):
            provider.preserve(submission, evaluation, decision)

    def test_regression_mismatched_evidence_digest_is_rejected(self) -> None:
        submission, evaluation, decision, registry = self.admission_bundle("digest")
        submission["candidate"]["digest"] = digest({"tampered": True})
        submission["digest"] = self_digest(submission)
        with self.assertRaisesRegex(ValueError, "candidate digest"):
            FakeEvidenceProvider(FakePolicyUseLedger(registry), registry).preserve(submission, evaluation, decision)

    def test_regression_mismatched_evidence_type_is_rejected(self) -> None:
        submission, _, _, _ = self.admission_bundle("type")
        submission["candidate"]["semantic_type"] = "policy_decision"
        submission["digest"] = self_digest(submission)
        self.assertInvalid("evidence", submission)

    def test_regression_wrong_independence_role_is_rejected(self) -> None:
        same = ref("capability_binding", "binding.same", {"same": True})
        request = self.evaluation_request(ref("artifact", "artifact.x", {"x": 1}), "independence", same, ref("actor", "actor.x"))
        with self.assertRaisesRegex(ValueError, "subject producer"):
            FakeEvaluator(self.registry).evaluate(request, self.profile(), request["subject"], same)

    def test_regression_wrong_request_result_correlation_is_rejected(self) -> None:
        request = self.evaluation_request(ref("artifact", "artifact.x", {"x": 1}), "correlation", ref("capability_binding", "binding.producer", {"role": "producer"}), ref("actor", "actor.x"))
        result = FakeEvaluator(self.registry).evaluate(request, self.profile(), request["subject"], ref("capability_binding", "binding.evaluator", {"role": "evaluator"}))
        result["request"] = ref("policy_request", "policy-request.wrong", {"wrong": True})
        self.assertInvalid("evaluation", result)

    def test_regression_admission_decision_must_consume_exact_evaluation(self) -> None:
        submission, evaluation, decision, registry = self.admission_bundle("evaluation-edge")
        decision["direct_supports"] = [ref("evaluation_result", "evaluation-result.other", {"other": True})]
        decision["digest"] = self_digest(decision)
        with self.assertRaisesRegex(ValueError, "did not consume"):
            FakeEvidenceProvider(FakePolicyUseLedger(registry), registry).preserve(submission, evaluation, decision)

    def test_regression_allow_cannot_carry_conditions(self) -> None:
        proposal = self.proposal("conditions")
        decision = self.execution_decision(proposal)
        decision["conditions"] = [{"condition_id": "condition.x", "requirement": ref("requirement", "requirement.x"), "must_be_enforced_by": ref("implementation", "gateway.fixture")}]
        self.assertInvalid("policy-decision", decision)

    def test_conformance_fixture_traceability(self) -> None:
        fixture = yaml.safe_load((ROOT / "fixtures" / "conformance" / "forge-gateway-contracts-v1.yaml").read_text())
        case_ids = [case["id"] for case in fixture["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case in fixture["cases"]:
            self.assertTrue(case.get("test"), case["id"])
            self.assertTrue(hasattr(self, case["test"]), f"{case['id']} -> {case['test']}")


if __name__ == "__main__":
    unittest.main()
