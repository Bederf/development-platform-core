"""Fail-closed completion policy for the bounded review workflow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


@dataclass(frozen=True)
class CompletionDecision:
    """Whether the supplied evidence satisfies the completion prerequisites."""

    eligible: bool
    reason: str


def assess_completion(
    cycle: Mapping[str, object],
    *,
    requirements_satisfied: bool,
    independent_review_result: Mapping[str, object] | None,
    focused_tests_passed: bool,
    live_verification_passed: bool,
    evidence_integrity_verified: bool,
    before_after_evidence_present: bool,
    unresolved_blockers: int,
    forge_status: str,
    forge_required: bool = True,
    verification_mode: str = "live",
    qualification_evidence_passed: bool = False,
    independent_review_required: bool = True,
) -> CompletionDecision:
    """Evaluate completion prerequisites without granting completion authority."""

    expected_action = "forge_verify" if independent_review_required else "complete"
    if cycle.get("outcome") not in {"PASS", "PASS_WITH_ADVISORIES"} or cycle.get("next_action") != expected_action:
        return CompletionDecision(False, f"review cycle has not reached required action: {expected_action}")
    if cycle.get("status") != "PASSED":
        return CompletionDecision(False, "review cycle status is not PASSED")
    if not requirements_satisfied:
        return CompletionDecision(False, "acceptance criteria are not deterministically satisfied")
    if independent_review_required:
        independent_review_error = _validate_independent_review(cycle, independent_review_result)
        if independent_review_error is not None:
            return CompletionDecision(False, independent_review_error)
    if not focused_tests_passed:
        return CompletionDecision(False, "focused tests did not pass")
    if verification_mode == "live":
        if not live_verification_passed:
            return CompletionDecision(False, "live verification evidence is missing")
    elif verification_mode == "qualification":
        if not qualification_evidence_passed:
            return CompletionDecision(False, "qualification verification evidence is missing")
    else:
        return CompletionDecision(False, "verification mode is invalid")
    if not evidence_integrity_verified:
        return CompletionDecision(False, "evidence persistence/audit integrity is unverified")
    if not before_after_evidence_present:
        return CompletionDecision(False, "applicable before/after evidence is missing")
    if not isinstance(unresolved_blockers, int) or isinstance(unresolved_blockers, bool):
        return CompletionDecision(False, "unresolved blocker count is invalid")
    if unresolved_blockers > 0:
        return CompletionDecision(False, "unresolved blockers remain")
    if forge_required and forge_status != "PASSED":
        return CompletionDecision(False, "Forge verification has not passed")
    if not forge_required and forge_status not in {"NOT_REQUIRED", "SKIPPED", "PASSED"}:
        return CompletionDecision(False, "Forge status is invalid for a non-Forge phase")
    return CompletionDecision(True, "all completion prerequisites are satisfied")


def _validate_independent_review(
    cycle: Mapping[str, object],
    result: Mapping[str, object] | None,
) -> str | None:
    """Validate actual reviewer evidence instead of trusting a boolean."""

    if not isinstance(result, Mapping):
        return "independent review result is missing"

    schema_path = Path(__file__).parents[1] / "contracts" / "code-review-result.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(dict(result)),
        key=lambda error: list(error.path),
    )
    if errors:
        return f"independent review result is invalid: {errors[0].message}"
    if result.get("independence") != "independent":
        return "review result is not independent"
    if result.get("disposition") not in {"PASS", "PASS_WITH_ADVISORIES"}:
        return "independent review did not pass"
    if cycle.get("review_result_ref") != result.get("review_id"):
        return "review cycle does not reference the independent review result"

    providers = result.get("providers")
    selected = providers.get("selected") if isinstance(providers, Mapping) else None
    if not isinstance(selected, list) or not selected:
        return "independent review has no selected provider"
    if all(str(provider).strip().lower() in {"evidence_reviewer", "evidence-reviewer"} for provider in selected):
        return "deterministic evidence aggregation cannot satisfy independent review"

    evidence = result.get("evidence")
    if not isinstance(evidence, list) or len(evidence) < 3:
        return "independent review evidence is incomplete"
    return None
