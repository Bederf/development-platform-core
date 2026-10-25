"""Deterministic comparison of GSD baseline and candidate strategies."""

from __future__ import annotations

from typing import Mapping


def compare_metrics(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    directions: Mapping[str, str],
    *,
    guardrails: Mapping[str, bool],
) -> str:
    """Return an outcome without permitting efficiency to override safety gates."""
    required = {"correctness_preserved", "verification_preserved", "evidence_complete", "regressions_within_limit"}
    if not required.issubset(guardrails):
        raise ValueError("all evaluation guardrails are required")
    if not all(guardrails.values()):
        return "rejected_by_guardrail"
    if set(baseline) != set(candidate) or set(baseline) != set(directions):
        raise ValueError("baseline, candidate, and directions must contain the same metrics")
    better = worse = False
    for metric, old in baseline.items():
        new = candidate[metric]
        if directions[metric] == "higher_is_better":
            better |= new > old
            worse |= new < old
        elif directions[metric] == "lower_is_better":
            better |= new < old
            worse |= new > old
        else:
            raise ValueError(f"unsupported direction for {metric!r}")
    if better and not worse:
        return "candidate_better"
    if worse and not better:
        return "baseline_better"
    return "equivalent" if not better and not worse else "inconclusive"


def pattern_is_candidate_eligible(pattern: Mapping[str, object]) -> bool:
    """Require independent, reproducible evidence before evaluation promotion."""
    strength = pattern.get("strength")
    if not isinstance(strength, Mapping):
        return False
    independence = strength.get("independence_proof")
    session_refs = independence.get("session_record_refs", ()) if isinstance(independence, Mapping) else ()
    session_keys = {(item.get("id"), item.get("version")) for item in session_refs if isinstance(item, Mapping)}
    execution_ids = independence.get("execution_ids", ()) if isinstance(independence, Mapping) else ()
    independence_proven = isinstance(independence, Mapping) and (
        len(session_refs) >= 3 and len(session_keys) >= 3
        and len(execution_ids) >= 3 and len(set(execution_ids)) >= 3
        and independence.get("lineage_checked") is True and bool(independence.get("attestation_ref"))
    )
    return (
        strength.get("evidence_level", 0) >= 3
        and strength.get("independent_session_count", 0) >= 3
        and strength.get("reproducible") is True
        and strength.get("candidate_eligible") is True
        and pattern.get("confidence") in {"high", "very_high"}
        and independence_proven
    )


def experimental_independence_is_proven(records: list[Mapping[str, object]]) -> bool:
    """Reject shared fixtures, cohort leakage, and copied experimental outputs."""
    required = {"cohort", "session_id", "execution_id", "fixture_id", "output_digest"}
    if not records or any(not required.issubset(record) for record in records):
        return False
    if {record["cohort"] for record in records} != {"baseline", "candidate"}:
        return False
    fields = tuple(tuple(record[field] for record in records) for field in required - {"cohort"})
    if any(len(set(values)) != len(values) for values in fields):
        return False
    for field in ("session_id", "execution_id"):
        cohorts = {record[field]: record["cohort"] for record in records}
        if len(cohorts) != len(records):
            return False
    return True
