"""Deterministic acceptance-criteria and evidence gate for GSD reviews."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RequirementGateDecision:
    eligible: bool
    unresolved_refs: tuple[str, ...]
    reason: str


def assess_requirements(
    requirements: Iterable[Mapping[str, object]],
    *,
    mandatory_requirement_refs: Iterable[str],
    available_evidence: Iterable[str],
    unresolved_blockers: int,
) -> RequirementGateDecision:
    """Require the canonical criteria set to be fully satisfied and evidenced."""

    mandatory = {str(ref).strip() for ref in mandatory_requirement_refs if str(ref).strip()}
    available = {str(ref) for ref in available_evidence}
    submitted = list(requirements)
    submitted_refs = [str(item.get("requirement_ref") or "").strip() for item in submitted]
    unresolved: list[str] = []
    if not mandatory:
        return RequirementGateDecision(False, ("no-mandatory-requirements",), "canonical acceptance criteria are absent")
    if len(submitted_refs) != len(set(submitted_refs)):
        unresolved.append("duplicate-requirement-ref")
    unresolved.extend(f"missing:{ref}" for ref in sorted(mandatory - set(submitted_refs)))
    unresolved.extend(f"unexpected:{ref}" for ref in sorted((set(submitted_refs) - mandatory) - {""}))
    for requirement in submitted:
        ref = str(requirement.get("requirement_ref") or "").strip()
        if not ref:
            unresolved.append("missing-requirement-ref")
            continue
        if ref not in mandatory:
            continue
        if requirement.get("status") != "satisfied":
            unresolved.append(ref)
            continue
        evidence_refs = requirement.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            unresolved.append(ref)
            continue
        if any(str(evidence) not in available for evidence in evidence_refs):
            unresolved.append(ref)

    if not isinstance(unresolved_blockers, int) or isinstance(unresolved_blockers, bool) or unresolved_blockers > 0:
        return RequirementGateDecision(False, tuple(unresolved), "unresolved blockers remain")
    if unresolved:
        return RequirementGateDecision(False, tuple(dict.fromkeys(unresolved)), "acceptance criteria are not fully evidenced")
    return RequirementGateDecision(True, (), "all acceptance criteria are satisfied and evidence-linked")
