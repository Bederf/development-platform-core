"""Pure conformance evaluation for the candidate governed-delegation family.

This module only evaluates supplied delegation records. It does not resolve
providers, authorize actions, execute work, admit evidence, or verify results.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence


# These dimensions intentionally overlap: a status can be terminal while
# still being unsafe for aggregation (for example FAILED or TIMED_OUT).
UNSAFE_STATUSES = {"DECLARED", "RUNNING", "FAILED", "PARTIAL", "TIMED_OUT", "CANCELLED", "UNKNOWN", "BLOCKED"}
TERMINAL_STATUSES = {"SUCCEEDED", "VERIFIED", "FAILED", "PARTIAL", "TIMED_OUT", "CANCELLED", "UNKNOWN", "BLOCKED"}


@dataclass(frozen=True)
class ConformanceFinding:
    code: str
    detail: str


@dataclass(frozen=True)
class ConformanceResult:
    status: str
    findings: tuple[ConformanceFinding, ...]


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _safe_digest(value: Any) -> str | None:
    try:
        return canonical_digest(value)
    except (TypeError, ValueError):
        return None


def evaluate(
    delegation_set: Mapping[str, Any],
    children: Sequence[Mapping[str, Any]],
    aggregation: Mapping[str, Any],
    *,
    objective_payloads: Mapping[str, Any] | None = None,
    available_capabilities: set[str] | None = None,
    authority_scope_payloads: Mapping[str, Mapping[str, Any]] | None = None,
    result_records: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    as_of: str | None = None,
) -> ConformanceResult:
    """Evaluate cross-record candidate invariants fail-closed."""

    findings: list[ConformanceFinding] = []
    if not isinstance(delegation_set, Mapping):
        return ConformanceResult("BLOCKED", (ConformanceFinding("DELEGATION_SET_INVALID", "delegation set must be an object"),))
    if not isinstance(aggregation, Mapping):
        return ConformanceResult("BLOCKED", (ConformanceFinding("AGGREGATION_INVALID", "aggregation must be an object"),))
    if not isinstance(children, Sequence) or isinstance(children, (str, bytes, bytearray)):
        return ConformanceResult("BLOCKED", (ConformanceFinding("CHILDREN_INVALID", "children must be an array"),))
    valid_children: list[Mapping[str, Any]] = []
    for child_record in children:
        if not isinstance(child_record, Mapping):
            findings.append(ConformanceFinding("CHILD_INVALID", "child record must be an object"))
            continue
        valid_children.append(child_record)
    children = valid_children
    expected_children = delegation_set.get("expected_children", [])
    if not isinstance(expected_children, Sequence) or isinstance(expected_children, (str, bytes, bytearray)):
        findings.append(ConformanceFinding("EXPECTED_CHILDREN_INVALID", "expected_children must be an array"))
        expected_children = []
    expected_list = [str(child_id) for child_id in expected_children]
    expected = set(expected_list)
    child_ids = [str(child.get("child_id")) for child in children]
    observed = set(child_ids)
    if len(child_ids) != len(observed):
        findings.append(ConformanceFinding("DUPLICATE_CHILD", "more than one observation uses the same child identity"))
    if len(expected_list) != len(expected):
        findings.append(ConformanceFinding("DUPLICATE_EXPECTED_CHILD", "expected child set contains duplicate identities"))
    aggregation_status = aggregation.get("aggregation_status")
    if aggregation_status != "COMPLETE":
        findings.append(
            ConformanceFinding(
                "AGGREGATION_STATUS_NOT_COMPLETE",
                f"declared={aggregation_status!r}",
            )
        )

    def reference_ids(field: str) -> set[str]:
        identifiers: set[str] = set()
        references = aggregation.get(field, [])
        if not isinstance(references, Sequence) or isinstance(references, (str, bytes, bytearray)):
            findings.append(ConformanceFinding("REFERENCE_LIST_INVALID", f"field={field}"))
            return identifiers
        for reference in references:
            if not isinstance(reference, Mapping):
                findings.append(ConformanceFinding("REFERENCE_INVALID", f"field={field}"))
                continue
            identifier = reference.get("id")
            if not isinstance(identifier, str) or not identifier:
                findings.append(ConformanceFinding("REFERENCE_ID_MISSING", f"field={field}"))
                continue
            identifiers.add(identifier)
        return identifiers

    declared_expected = reference_ids("expected_child_refs")
    declared_observed = reference_ids("observed_child_refs")
    included = reference_ids("included_child_refs")
    if declared_expected != expected:
        findings.append(ConformanceFinding("AGGREGATION_EXPECTED_SET_INVALID", "aggregation expected set differs from delegation set"))
    if declared_observed != observed:
        findings.append(ConformanceFinding("AGGREGATION_OBSERVED_SET_INVALID", "aggregation observed set differs from child observations"))
    if included != expected:
        findings.append(ConformanceFinding("AGGREGATION_INCLUDED_SET_INVALID", "aggregation included set differs from expected child set"))

    expected_digest = _safe_digest(sorted(expected))
    if expected_digest is None or delegation_set.get("expected_set_digest") != expected_digest:
        findings.append(ConformanceFinding("EXPECTED_SET_DIGEST_INVALID", "expected child set digest does not match canonical membership"))

    objective_ref = delegation_set.get("objective_ref", {})
    if not isinstance(objective_ref, Mapping):
        findings.append(ConformanceFinding("OBJECTIVE_REFERENCE_INVALID", "objective reference must be an object"))
        objective_ref = {}
    if objective_payloads is None:
        findings.append(ConformanceFinding("OBJECTIVE_UNRESOLVED", "objective reference was not resolved"))
    else:
        objective_id = str(objective_ref.get("id"))
        if objective_id not in objective_payloads:
            findings.append(ConformanceFinding("OBJECTIVE_MISSING", "objective reference cannot be resolved"))
        else:
            resolved_objective_digest = _safe_digest(objective_payloads[objective_id])
            if resolved_objective_digest is None:
                findings.append(ConformanceFinding("OBJECTIVE_DIGEST_INVALID", "resolved objective is not valid canonical JSON"))
            elif delegation_set.get("objective_digest") != resolved_objective_digest:
                findings.append(ConformanceFinding("OBJECTIVE_DIGEST_INVALID", "objective digest does not match resolved objective"))

    if available_capabilities is None:
        findings.append(ConformanceFinding("CAPABILITIES_UNRESOLVED", "required capabilities were not resolved"))
    else:
        required: set[str] = set()
        for reference in delegation_set.get("required_capability_refs", []):
            if not isinstance(reference, Mapping) or not isinstance(reference.get("id"), str) or not reference.get("id"):
                findings.append(ConformanceFinding("CAPABILITY_REFERENCE_INVALID", "required capability reference is malformed"))
                continue
            required.add(reference["id"])
        missing_capabilities = required - available_capabilities
        if missing_capabilities:
            findings.append(ConformanceFinding("CAPABILITY_REQUIREMENT_UNSATISFIED", f"missing={sorted(missing_capabilities)}"))

    scope = delegation_set.get("scope", {})
    authority_scope = delegation_set.get("authority_scope_ref", {})
    if not isinstance(scope, Mapping):
        findings.append(ConformanceFinding("SCOPE_INVALID", "delegation scope must be an object"))
        scope = {}
    if not isinstance(authority_scope, Mapping):
        findings.append(ConformanceFinding("AUTHORITY_SCOPE_UNRESOLVED", "authority scope reference must be an object"))
        authority_scope = {}
    if authority_scope.get("scope_ref") != scope.get("scope_id"):
        findings.append(ConformanceFinding("AUTHORITY_SCOPE_MISMATCH", "authority scope exceeds delegation scope"))
    if authority_scope_payloads is None:
        findings.append(ConformanceFinding("AUTHORITY_SCOPE_UNRESOLVED", "authority scope reference was not resolved"))
    else:
        resolved_scope = authority_scope_payloads.get(str(authority_scope.get("id")))
        if resolved_scope is None:
            findings.append(ConformanceFinding("AUTHORITY_SCOPE_UNRESOLVED", "authority scope reference cannot be resolved"))
        elif resolved_scope != scope:
            findings.append(ConformanceFinding("AUTHORITY_SCOPE_MISMATCH", "resolved authority scope differs from delegation scope"))

    deadline = delegation_set.get("deadline")
    if as_of is not None and not deadline:
        findings.append(ConformanceFinding("DEADLINE_UNRESOLVED", "delegation deadline is required when evaluating as_of"))
    if deadline and as_of is None:
        findings.append(ConformanceFinding("DEADLINE_AS_OF_UNRESOLVED", "deadline cannot be evaluated without an as_of timestamp"))
    if as_of and deadline:
        try:
            after_deadline = datetime.fromisoformat(as_of.replace("Z", "+00:00")) > datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            findings.append(ConformanceFinding("DEADLINE_TIMESTAMP_INVALID", "as_of or deadline is not a valid RFC 3339 timestamp"))
            after_deadline = False
        if after_deadline:
            unresolved_after_deadline = False
            for child in children:
                if child.get("child_id") in expected and child.get("status") not in {"SUCCEEDED", "VERIFIED"}:
                    unresolved_after_deadline = True
                completed_at = child.get("completed_at") if "completed_at" in child else child.get("finished_at")
                if completed_at:
                    try:
                        completed_after_deadline = datetime.fromisoformat(completed_at.replace("Z", "+00:00")) > datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                    except (AttributeError, TypeError, ValueError):
                        findings.append(ConformanceFinding("CHILD_TIMESTAMP_INVALID", f"child={child.get('child_id')}"))
                        completed_after_deadline = False
                    if completed_after_deadline:
                        findings.append(ConformanceFinding("DEADLINE_EXCEEDED", f"child={child.get('child_id')} completed after delegation deadline"))
            if unresolved_after_deadline:
                findings.append(ConformanceFinding("DEADLINE_EXCEEDED", "required child remained unresolved after delegation deadline"))

    if expected - observed:
        findings.append(ConformanceFinding("MISSING_EXPECTED_CHILD", f"missing={sorted(expected - observed)}"))
    if observed - expected:
        findings.append(ConformanceFinding("UNEXPECTED_CHILD", f"unexpected={sorted(observed - expected)}"))
    if observed - included:
        findings.append(ConformanceFinding("OBSERVED_NOT_INCLUDED", f"omitted={sorted(observed - included)}"))
    if included - observed:
        findings.append(ConformanceFinding("INCLUDED_NOT_OBSERVED", f"invalid_included={sorted(included - observed)}"))

    if result_records is None:
        result_records = {}
    elif not isinstance(result_records, Mapping):
        findings.append(ConformanceFinding("RESULT_RECORDS_UNRESOLVED", "result records must be an object"))
        result_records = {}
    for child in children:
        child_id = str(child.get("child_id"))
        if child.get("delegation_id") != delegation_set.get("delegation_id") or child.get("revision") != delegation_set.get("revision"):
            findings.append(ConformanceFinding("REVISION_BINDING_INVALID", f"child={child_id}"))
        if child.get("scope") != scope:
            findings.append(ConformanceFinding("CHILD_SCOPE_INVALID", f"child={child_id}"))
        parent_ref = child.get("parent_ref")
        if not isinstance(parent_ref, Mapping):
            findings.append(ConformanceFinding("PARENT_BINDING_INVALID", f"child={child_id}"))
        elif (
            parent_ref.get("id") != delegation_set.get("delegation_id")
            or parent_ref.get("version") != delegation_set.get("version")
        ):
            findings.append(ConformanceFinding("PARENT_BINDING_INVALID", f"child={child_id}"))
        status = child.get("status")
        result_refs = child.get("result_refs", [])
        if not isinstance(result_refs, Sequence) or isinstance(result_refs, (str, bytes, bytearray)):
            findings.append(ConformanceFinding("RESULT_REFERENCES_INVALID", f"child={child_id}"))
            result_refs = []
        if status in TERMINAL_STATUSES and not result_refs:
            findings.append(ConformanceFinding("TERMINAL_RESULT_MISSING", f"child={child_id}"))
        outcomes: set[str] = set()
        for result_ref in result_refs:
            if not isinstance(result_ref, Mapping):
                findings.append(ConformanceFinding("RESULT_REFERENCE_INVALID", f"child={child_id}"))
                continue
            result = result_records.get((str(result_ref.get("id")), str(result_ref.get("version"))))
            if result is None:
                findings.append(ConformanceFinding("RESULT_MISSING", f"child={child_id}"))
                findings.append(ConformanceFinding("RESULT_OUTCOME_UNRESOLVED", f"child={child_id}"))
                continue
            if result.get("digest") != result_ref.get("digest"):
                findings.append(ConformanceFinding("RESULT_DIGEST_INVALID", f"child={child_id}"))
            if result.get("child_id") != child_id:
                findings.append(ConformanceFinding("RESULT_CHILD_MISMATCH", f"child={child_id}"))
            if result.get("delegation_id") is not None and result.get("delegation_id") != delegation_set.get("delegation_id"):
                findings.append(ConformanceFinding("RESULT_DELEGATION_MISMATCH", f"child={child_id}"))
            if result.get("revision") is not None and result.get("revision") != child.get("revision"):
                findings.append(ConformanceFinding("RESULT_REVISION_INVALID", f"child={child_id}"))
            if result.get("status") is not None and result.get("status") != status:
                findings.append(ConformanceFinding("RESULT_STATUS_MISMATCH", f"child={child_id}"))
            if status in TERMINAL_STATUSES and not result.get("outcome_digest"):
                findings.append(ConformanceFinding("RESULT_OUTCOME_UNRESOLVED", f"child={child_id}"))
            if result.get("outcome_digest"):
                outcomes.add(str(result["outcome_digest"]))
        if len(outcomes) > 1:
            findings.append(ConformanceFinding("CONTRADICTORY_RESULTS", f"child={child_id}"))
        if status in UNSAFE_STATUSES:
            findings.append(ConformanceFinding("UNSAFE_CHILD_STATUS", f"child={child_id}, status={status}"))
        if status == "VERIFIED" and not child.get("provider_observation_ref"):
            findings.append(ConformanceFinding("VERIFICATION_EVIDENCE_MISSING", f"child={child_id}"))

    if findings:
        return ConformanceResult("BLOCKED", tuple(sorted(findings, key=lambda finding: (finding.code, finding.detail))))
    return ConformanceResult("COMPLETE", ())
