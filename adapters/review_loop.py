"""Provider-neutral policy for the bounded GSD review/correction loop.

This module plans the next governed action from an existing ReviewCycle. It
does not execute agents, invoke providers, mutate a worktree, or authorize
completion. Those runtime concerns remain outside the Phase 001 Core boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ReviewLoopPolicyError(ValueError):
    """Raised when a cycle cannot be safely advanced."""


@dataclass(frozen=True)
class ReviewLoopDecision:
    """The next workflow action, without execution authority."""

    action: str
    terminal: bool
    requires_new_revision: bool
    reason: str


def plan_next_action(cycle: Mapping[str, object]) -> ReviewLoopDecision:
    """Plan the next bounded action from a validated ReviewCycle payload."""

    required = {"cycle_number", "max_cycles", "outcome", "next_action", "status"}
    missing = required - set(cycle)
    if missing:
        raise ReviewLoopPolicyError(f"cycle missing fields: {sorted(missing)}")

    cycle_number = cycle["cycle_number"]
    max_cycles = cycle["max_cycles"]
    if not isinstance(cycle_number, int) or isinstance(cycle_number, bool):
        raise ReviewLoopPolicyError("cycle_number must be an integer")
    if max_cycles != 3 or cycle_number < 1 or cycle_number > max_cycles:
        raise ReviewLoopPolicyError("cycle must be within the three-cycle bound")

    outcome = cycle["outcome"]
    next_action = cycle["next_action"]
    status = cycle["status"]
    independent_review_required = cycle.get("independent_review_required", True)
    if not isinstance(independent_review_required, bool):
        raise ReviewLoopPolicyError("independent_review_required must be boolean")

    if outcome == "PASS":
        expected_action = "forge_verify" if independent_review_required else "complete"
        if next_action != expected_action or status != "PASSED":
            raise ReviewLoopPolicyError("PASS must route to its risk-derived completion path")
        return ReviewLoopDecision(
            action=expected_action,
            terminal=not independent_review_required,
            requires_new_revision=False,
            reason=(
                "review passed; independent Forge verification is required"
                if independent_review_required
                else "review passed; risk profile does not require independent review"
            ),
        )

    if outcome == "CHANGES_REQUIRED":
        if not cycle.get("finding_refs"):
            raise ReviewLoopPolicyError("CHANGES_REQUIRED requires finding references")
        if cycle_number < max_cycles:
            if next_action not in {"implement_fix", "re_review"} or status != "OPEN":
                raise ReviewLoopPolicyError("an open cycle must return to implementation or re-review")
            return ReviewLoopDecision(
                action=next_action,
                terminal=False,
                requires_new_revision=next_action == "implement_fix",
                reason="findings remain; produce a new revision before re-review",
            )
        if next_action not in {"escalate", "stop"} or status != "ESCALATED":
            raise ReviewLoopPolicyError("the third unsuccessful cycle must escalate or stop")
        return ReviewLoopDecision(
            action=next_action,
            terminal=True,
            requires_new_revision=False,
            reason="maximum correction cycles exhausted",
        )

    if outcome in {"INCOMPLETE_REVIEW", "BLOCKED", "ESCALATED"}:
        if next_action not in {"escalate", "stop"} or status != "ESCALATED":
            raise ReviewLoopPolicyError("incomplete or blocked review must escalate or stop")
        return ReviewLoopDecision(
            action=next_action,
            terminal=True,
            requires_new_revision=False,
            reason="review cannot safely advance",
        )

    raise ReviewLoopPolicyError(f"unsupported cycle outcome: {outcome!r}")
