"""Provider-neutral fake code-review adapter for conformance testing.

This is deliberately not an AI runtime. It proves the review-result boundary
and its fail-closed independence/evidence behavior before a real provider is
connected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Mapping


class CodeReviewError(ValueError):
    """Raised when a review frame cannot produce a governed result."""


class FakeCodeReviewAgent:
    """Deterministic fake provider that emits a review result without I/O."""

    def review(
        self,
        frame: Mapping[str, Any],
        *,
        findings: Iterable[Mapping[str, Any]] = (),
        evidence: Iterable[Mapping[str, str]] = (),
    ) -> dict[str, Any]:
        attempt_ref = str(frame.get("attempt_ref") or frame.get("frame_id") or "").strip()
        if not attempt_ref:
            raise CodeReviewError("review frame requires attempt_ref or frame_id")

        independence = str(frame.get("independence") or "unknown")
        if independence not in {"independent", "self_review", "unknown"}:
            raise CodeReviewError("invalid review independence")

        evidence_rows = [dict(item) for item in evidence]
        finding_rows = [dict(item) for item in findings]
        for row in evidence_rows:
            if not str(row.get("kind") or "").strip() or not str(row.get("ref") or "").strip():
                raise CodeReviewError("each evidence item requires kind and ref")
        for row in finding_rows:
            self._validate_finding(row)

        if independence == "self_review":
            finding_rows.append({
                "id": "review.independence.self-review",
                "severity": "blocker",
                "confidence": "very_high",
                "title": "Review is not independent",
                "description": "The implementation and review share the same context.",
                "category": "governance",
                "evidence_ref": "frame.independence",
                "recommendation": "Run the review in a fresh context separate from implementation.",
                "source": "fake-code-reviewer",
            })

        insufficient_evidence = len(evidence_rows) < 3
        if insufficient_evidence:
            finding_rows.append({
                "id": "review.evidence.insufficient",
                "severity": "blocker",
                "confidence": "very_high",
                "title": "Insufficient review evidence",
                "description": "At least three evidence sources are required for an independent review.",
                "category": "evidence",
                "evidence_ref": "frame.evidence",
                "recommendation": "Provide the specification, implementation diff, and verification evidence.",
                "source": "fake-code-reviewer",
            })

        if independence in {"self_review", "unknown"}:
            disposition = "BLOCKED" if independence == "self_review" else "INCOMPLETE_REVIEW"
        elif insufficient_evidence:
            disposition = "INCOMPLETE_REVIEW"
        elif any(row["severity"] in {"blocker", "major"} for row in finding_rows):
            disposition = "CHANGES_REQUIRED"
        elif any(row["severity"] in {"minor", "advisory"} for row in finding_rows):
            disposition = "PASS_WITH_ADVISORIES"
        else:
            disposition = "PASS"

        return {
            "schema": "code-review-result.v1",
            "review_id": str(frame.get("review_id") or f"review:{attempt_ref}"),
            "attempt_ref": attempt_ref,
            "independence": independence,
            "classification": dict(frame.get("classification") or {}),
            "providers": {
                "considered": ["development-platform-code-reviewer"],
                "selected": ["development-platform-code-reviewer"],
                "skipped": [],
            },
            "findings": finding_rows,
            "disposition": disposition,
            "evidence": evidence_rows,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _validate_finding(finding: Mapping[str, Any]) -> None:
        required = {"id", "severity", "confidence", "title", "description", "category", "evidence_ref", "recommendation", "source"}
        missing = required - set(finding)
        if missing:
            raise CodeReviewError(f"finding missing fields: {sorted(missing)}")
        if finding["severity"] not in {"blocker", "major", "minor", "advisory"}:
            raise CodeReviewError("invalid finding severity")
        if finding["confidence"] not in {"very_high", "high", "medium", "low", "very_low"}:
            raise CodeReviewError("invalid finding confidence")
