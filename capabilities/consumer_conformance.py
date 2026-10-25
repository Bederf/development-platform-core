"""Evidence-backed conformance checks for thin kernel consumers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping


Outcome = Literal["satisfied", "failed", "unknown", "expired"]
KernelOperation = Literal["resolve_requirements", "admit_candidates", "plan_binding"]


@dataclass(frozen=True)
class KernelCall:
    operation: KernelOperation
    outputs: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class RecordSnapshot:
    reference: Mapping[str, Any]
    before_digest: str
    after_digest: str


@dataclass(frozen=True)
class ConsumerEvidence:
    evidence_id: str
    consumer: Mapping[str, Any]
    external_inputs: tuple[Mapping[str, Any], ...]
    kernel_calls: tuple[KernelCall, ...]
    presented_outputs: tuple[Mapping[str, Any], ...]
    consumer_created_records: tuple[Mapping[str, Any], ...]
    snapshots: tuple[RecordSnapshot, ...]
    issuer: str
    authority_binding: Mapping[str, Any]
    validity_scope: Mapping[str, Any]
    observed_at: datetime
    valid_until: datetime | None = None
    digest: str = ""

    def expected_digest(self) -> str:
        material = {
            "evidence_id": self.evidence_id,
            "consumer": dict(self.consumer),
            "external_inputs": [dict(item) for item in self.external_inputs],
            "kernel_calls": [
                {"operation": call.operation, "outputs": [dict(item) for item in call.outputs]}
                for call in self.kernel_calls
            ],
            "presented_outputs": [dict(item) for item in self.presented_outputs],
            "consumer_created_records": [dict(item) for item in self.consumer_created_records],
            "snapshots": [
                {"reference": dict(item.reference), "before_digest": item.before_digest, "after_digest": item.after_digest}
                for item in self.snapshots
            ],
            "issuer": self.issuer,
            "authority_binding": dict(self.authority_binding),
            "validity_scope": dict(self.validity_scope),
            "observed_at": self.observed_at.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class ConsumerFinding:
    code: str
    detail: str


@dataclass(frozen=True)
class ConsumerConformanceAssessment:
    outcome: Outcome
    findings: tuple[ConsumerFinding, ...]
    evaluated_at: datetime


class KernelConsumptionEvaluator:
    def __init__(
        self,
        *,
        evaluator_id: str,
        recognized_evidence_issuers: Mapping[str, set[str] | frozenset[str]],
    ) -> None:
        self.evaluator_id = evaluator_id
        self.recognized_evidence_issuers = {
            issuer: frozenset(authorities)
            for issuer, authorities in recognized_evidence_issuers.items()
        }

    def evaluate(
        self, evidence: ConsumerEvidence, *, evaluated_at: datetime
    ) -> ConsumerConformanceAssessment:
        evaluated_at = _aware(evaluated_at)
        findings: list[ConsumerFinding] = []
        authority = evidence.authority_binding
        if not _typed_ref(authority, "authority_binding") or authority["id"] not in self.recognized_evidence_issuers.get(evidence.issuer, ()):
            findings.append(ConsumerFinding("EVIDENCE_AUTHORITY_UNRECOGNIZED", "Harness authority is not recognized"))
        if evidence.issuer == evidence.consumer.get("issuer"):
            findings.append(ConsumerFinding("SELF_CERTIFICATION", "Consumer cannot issue its own conformance evidence"))
        if evidence.digest != evidence.expected_digest():
            findings.append(ConsumerFinding("EVIDENCE_DIGEST_MISMATCH", "Evidence envelope was modified"))
        if _aware(evidence.observed_at) > evaluated_at:
            findings.append(ConsumerFinding("EVIDENCE_FUTURE", "Evidence was observed in the future"))
        expired = evidence.valid_until is not None and _aware(evidence.valid_until) < evaluated_at

        calls = list(evidence.kernel_calls)
        operations = [call.operation for call in calls]
        expected_order = ["resolve_requirements", "admit_candidates", "plan_binding"]
        if not calls:
            findings.append(ConsumerFinding("KERNEL_NOT_INVOKED", "Consumer supplied no kernel invocation evidence"))
        if any(operation not in expected_order for operation in operations):
            findings.append(ConsumerFinding("KERNEL_OPERATION_UNKNOWN", "Consumer invoked an unknown kernel operation"))
        elif operations != sorted(operations, key=expected_order.index):
            findings.append(ConsumerFinding("KERNEL_CALL_ORDER_INVALID", "Kernel operations are out of order"))

        kernel_outputs = [item for call in calls for item in call.outputs]
        output_digests = {_digest(item) for item in kernel_outputs}
        for presented in evidence.presented_outputs:
            if _digest(presented) not in output_digests:
                findings.append(ConsumerFinding("KERNEL_OUTPUT_REWRITTEN", "Presented output was not issued by the kernel"))
        if any(item.before_digest != item.after_digest for item in evidence.snapshots):
            findings.append(ConsumerFinding("KERNEL_RECORD_MUTATED", "A consumed kernel record was mutated"))

        prohibited = {"resolution_result", "conformance_claim", "compatibility_assessment", "policy_decision", "capability_binding"}
        for record in evidence.consumer_created_records:
            if record.get("entity_type") in prohibited or record.get("semantic_type") in prohibited:
                findings.append(ConsumerFinding("CONSUMER_DECISION_DUPLICATION", "Consumer created a kernel-owned decision record"))

        resolution_outputs = [item for call in calls if call.operation == "resolve_requirements" for item in call.outputs]
        if any(item.get("unresolved") for item in resolution_outputs) and any(op in operations for op in ("admit_candidates", "plan_binding")):
            findings.append(ConsumerFinding("UNRESOLVED_BYPASSED", "Consumer continued after unresolved requirements"))

        candidate_outputs = [item for call in calls if call.operation == "admit_candidates" for item in call.outputs]
        multiple = any(len(item.get("eligible_candidates", [])) > 1 for item in candidate_outputs)
        selections = [item for item in evidence.external_inputs if item.get("entity_type") == "selection_result" and item.get("outcome") == "selected"]
        policies = [item for item in evidence.external_inputs if item.get("semantic_type") == "policy_decision" and item.get("outcome") == "ALLOW"]
        if multiple and "plan_binding" in operations and not selections:
            findings.append(ConsumerFinding("SELECTION_INFERRED", "Multiple candidates were bound without external selection"))
        if "plan_binding" in operations and not policies:
            findings.append(ConsumerFinding("POLICY_INFERRED", "Binding was requested without external ALLOW policy"))
        for call in calls:
            if call.operation == "plan_binding" and any(item.get("lifecycle_status") != "proposed" for item in call.outputs):
                findings.append(ConsumerFinding("BINDING_ACTIVATED", "Consumer received or serialized a non-proposed binding"))

        if expired and not findings:
            return ConsumerConformanceAssessment("expired", (), evaluated_at)
        return ConsumerConformanceAssessment("failed" if findings else "satisfied", tuple(findings), evaluated_at)


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _typed_ref(value: Any, semantic_type: str) -> bool:
    return isinstance(value, Mapping) and value.get("semantic_type") == semantic_type and all(value.get(key) for key in ("id", "version"))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
