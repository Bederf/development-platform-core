"""Fail-closed projection from consumer Gateway types to Core v1 candidates."""

from __future__ import annotations

from typing import Any, Mapping


class ProjectionError(ValueError):
    """Raised when a consumer object cannot safely project to Core."""


def _required(mapping: Mapping[str, Any], field: str) -> Any:
    value = mapping.get(field)
    if value is None or value == "":
        raise ProjectionError(f"{field} is unavailable")
    return value


def project_policy_decision(request: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    for field in ("request_id", "session_id", "task_id", "capability", "arguments", "arguments_sha256"):
        _required(request, field)
    for field in ("decision_id", "decision", "policy_id", "policy_version", "issued_at", "expires_at"):
        _required(decision, field)
    if decision.get("decision") != "allow":
        raise ProjectionError("only an allow decision can project to execution")
    if not decision.get("decision_digest"):
        raise ProjectionError("decision_digest is unavailable")
    if not decision.get("authority_binding"):
        raise ProjectionError("authority_binding is external/unavailable")
    return {"candidate_type": "policy_decision", "authoritative": False, "request": dict(request), "decision": dict(decision)}


def project_execution_request(request: Mapping[str, Any], decision_candidate: Mapping[str, Any]) -> dict[str, Any]:
    if decision_candidate.get("candidate_type") != "policy_decision":
        raise ProjectionError("execution requires a policy decision candidate")
    if decision_candidate.get("authoritative") is not False:
        raise ProjectionError("policy candidate must remain non-authoritative")
    for field in ("request_id", "authorization_id", "session_id", "task_id", "capability", "arguments", "arguments_sha256", "timeout_seconds"):
        _required(request, field)
    for field in ("target", "baseline", "capability_binding"):
        _required(request, field)
    if request["authorization_id"] != decision_candidate["decision"]["decision_id"]:
        raise ProjectionError("authorization identity mismatch")
    return {"candidate_type": "engineering_execution", "authoritative": False, "request": dict(request), "policy": decision_candidate}
