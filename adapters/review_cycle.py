"""Fake ReviewCycle coordinator for contract conformance.

This is a deterministic test double, not a correction-loop runtime. It maps a
validated review result to coordination state so the GSD loop can be qualified
before a provider or execution runtime is connected.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .code_review_context import ReviewPackage


class ReviewCycleError(ValueError):
    """Raised when fake cycle coordination cannot produce governed state."""


class FakeReviewCycleCoordinator:
    """Create one validated ReviewCycle record from an injected review result."""

    MAX_CYCLES = 3

    def __init__(self, reviewer: Any) -> None:
        self._reviewer = reviewer
        self._finding_refs_by_cycle: dict[str, list[str]] = {}

    def run_cycle(
        self,
        package: ReviewPackage,
        *,
        task_ref: str,
        cycle_number: int,
        prior_cycle_ref: str | None = None,
        independent_review_required: bool = True,
    ) -> dict[str, Any]:
        if not task_ref.strip():
            raise ReviewCycleError("task_ref is required")
        if cycle_number < 1 or cycle_number > self.MAX_CYCLES:
            raise ReviewCycleError("cycle_number must be between 1 and 3")

        result = self._reviewer.review(package)
        if not isinstance(result, Mapping):
            raise ReviewCycleError("reviewer must return a review result object")
        findings = list(result.get("findings") or [])
        disposition = result.get("disposition")
        outcome = {
            "PASS": "PASS",
            "PASS_WITH_ADVISORIES": "PASS",
            "CHANGES_REQUIRED": "CHANGES_REQUIRED",
            "INCOMPLETE_REVIEW": "INCOMPLETE_REVIEW",
            "BLOCKED": "BLOCKED",
        }.get(disposition)
        if outcome is None:
            raise ReviewCycleError("review result has an unsupported disposition")

        if outcome == "PASS":
            next_action = "forge_verify" if independent_review_required else "complete"
            status = "PASSED"
            next_revision_ref = None
        elif outcome == "CHANGES_REQUIRED" and cycle_number < self.MAX_CYCLES:
            next_action = "implement_fix"
            status = "OPEN"
            next_revision_ref = f"revision-{cycle_number + 1:03d}"
        else:
            next_action = "escalate"
            status = "ESCALATED"
            next_revision_ref = None
            if outcome == "CHANGES_REQUIRED":
                outcome = "CHANGES_REQUIRED"
            else:
                outcome = "ESCALATED"

        finding_refs = [str(finding["id"]) for finding in findings]
        if not finding_refs and prior_cycle_ref:
            finding_refs = list(self._finding_refs_by_cycle.get(prior_cycle_ref, []))

        cycle = {
            "schema": "review-cycle.v1",
            "cycle_id": f"cycle-{cycle_number:03d}",
            "task_ref": task_ref,
            "revision_ref": package.attempt_ref,
            "cycle_number": cycle_number,
            "max_cycles": self.MAX_CYCLES,
            "prior_cycle_ref": prior_cycle_ref,
            "review_result_ref": str(result["review_id"]),
            "finding_refs": finding_refs,
            "outcome": outcome,
            "next_action": next_action,
            "independent_review_required": independent_review_required,
            "next_revision_ref": next_revision_ref,
            "verification_ref": None,
            "evidence_refs": [str(item["ref"]) for item in result["evidence"]],
            "status": status,
            "created_at": datetime.now(UTC).isoformat(),
        }
        schema = json.loads((Path(__file__).parents[1] / "contracts" / "review-cycle.v1.schema.json").read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(cycle),
            key=lambda error: list(error.path),
        )
        if errors:
            raise ReviewCycleError(f"invalid ReviewCycle: {errors[0].message}")
        self._finding_refs_by_cycle[cycle["cycle_id"]] = finding_refs
        return cycle
