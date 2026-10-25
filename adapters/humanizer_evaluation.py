"""Deterministic Humanizer review evaluation.

This evaluates supplied review and gate results. It does not inspect source
semantics, run Forge, approve a transformation, or activate Humanizer.
"""

from __future__ import annotations

from typing import Mapping


REVIEW_DIMENSIONS = frozenset(
    {"readability", "idiomaticity", "consistency", "simplicity", "maintainability"}
)
REQUIRED_GATES = frozenset(
    {"semantic_integrity", "lint", "tests", "forge_verification", "safeguard_preservation", "project_consistency"}
)


def evaluate_humanizer_review(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    gates: Mapping[str, bool],
    *,
    minimum_score: float = 3,
) -> str:
    """Compare Humanizer review scores without granting adoption authority."""
    if set(baseline) != REVIEW_DIMENSIONS or set(candidate) != REVIEW_DIMENSIONS:
        raise ValueError("baseline and candidate must contain all review dimensions")
    if set(gates) != REQUIRED_GATES:
        raise ValueError("all Humanizer review gates are required")
    if not all(isinstance(value, (int, float)) and 1 <= value <= 5 for value in (*baseline.values(), *candidate.values())):
        raise ValueError("review scores must be numbers from 1 to 5")
    if not all(isinstance(value, bool) for value in gates.values()):
        raise ValueError("review gates must be boolean")
    if not all(gates.values()):
        return "rejected_by_gate"
    if any(value < minimum_score for value in candidate.values()):
        return "rejected_by_review"

    improved = any(candidate[name] > baseline[name] for name in REVIEW_DIMENSIONS)
    worsened = any(candidate[name] < baseline[name] for name in REVIEW_DIMENSIONS)
    if improved and not worsened:
        return "candidate_better"
    if worsened and not improved:
        return "baseline_better"
    return "equivalent" if not improved and not worsened else "inconclusive"
