"""Fail-closed lifecycle validation for bounded assurance evidence.

This module composes the existing source snapshot and authority concepts. It
does not create authority, discover the worktree, invoke Git, or promote
evidence. A caller supplies immutable source snapshots and an explicit
promotion envelope; the validator determines whether the declared disposition
is internally supportable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .contract_authority import SourceArtifact, sha256_digest


ROOT = Path(__file__).parents[1]
DEFAULT_SCHEMA = ROOT / "contracts" / "assurance-evidence-promotion.v1.schema.json"
DISPOSITIONS = {"candidate", "promoted", "superseded", "orphaned", "invalid", "unresolved"}


class AssuranceEvidenceError(ValueError):
    """Raised for invalid lifecycle validator configuration."""


@dataclass(frozen=True)
class AssuranceEvidenceFinding:
    code: str
    detail: str
    blocking: bool = True


@dataclass(frozen=True)
class AssuranceEvidenceValidationResult:
    structural_valid: bool
    disposition: str | None
    reproducibility: str
    authoritative_eligible: bool
    findings: tuple[AssuranceEvidenceFinding, ...]


class AssuranceEvidenceLifecycleValidator:
    """Validate evidence lifecycle claims against supplied source snapshots."""

    def __init__(self, schema_path: str | Path | None = None) -> None:
        path = Path(schema_path) if schema_path else DEFAULT_SCHEMA
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def validate(
        self,
        record: Mapping[str, Any],
        *,
        sources: Mapping[tuple[str, str, str], SourceArtifact] | None = None,
        source_revision: str | None = None,
        authority_decision: Mapping[str, Any] | None = None,
    ) -> AssuranceEvidenceValidationResult:
        """Validate a record without reading repository state.

        Candidate records may refer to untracked sources, but are explicitly
        non-authoritative. Promoted records require every authority-critical
        reference to be tracked, digest-valid, and bound to one revision.
        """

        errors = tuple(sorted(self._format_error(error) for error in self._validator.iter_errors(dict(record))))
        disposition = record.get("disposition") if isinstance(record, Mapping) else None
        if errors:
            return AssuranceEvidenceValidationResult(
                False,
                disposition if isinstance(disposition, str) else None,
                "non_reproducible",
                False,
                tuple(AssuranceEvidenceFinding("SCHEMA_INVALID", error) for error in errors),
            )
        sources = sources or {}
        findings: list[AssuranceEvidenceFinding] = []
        refs = self._references(record)
        for label, ref, required in refs:
            if ref is None:
                if required:
                    findings.append(AssuranceEvidenceFinding("EVIDENCE_MISSING", f"required {label} reference is absent"))
                continue
            key = (ref["semantic_type"], ref["id"], ref["version"])
            source = sources.get(key)
            if source is None:
                findings.append(AssuranceEvidenceFinding("EVIDENCE_MISSING", f"{label} source is absent: {key}"))
                continue
            if source.content is None or sha256_digest(source.content) != source.digest or source.digest != ref["digest"]:
                findings.append(AssuranceEvidenceFinding("DIGEST_MISMATCH", f"{label} digest does not match source content: {key}"))
            if source.revision != record["source_revision"]:
                findings.append(AssuranceEvidenceFinding("SOURCE_REVISION_MISMATCH", f"{label} is bound to another revision: {key}"))
            if not source.tracked:
                blocking = disposition == "promoted"
                findings.append(AssuranceEvidenceFinding("SOURCE_NOT_REPRODUCIBLE", f"{label} is untracked: {key}", blocking))
            if label == "authority decision" and source.semantic_type != "promotion_record":
                findings.append(AssuranceEvidenceFinding("AUTHORITY_REFERENCE_INVALID", "authority decision must be a promotion_record"))

        if source_revision is not None and source_revision != record["source_revision"]:
            findings.append(AssuranceEvidenceFinding("SOURCE_REVISION_MISMATCH", "record revision differs from supplied revision"))

        referenced_digests = {ref["digest"] for _, ref, _ in refs if ref is not None}
        if set(record["provenance"]["source_digests"]) != referenced_digests:
            findings.append(AssuranceEvidenceFinding("DIGEST_SET_MISMATCH", "provenance digest set does not match referenced sources"))

        if disposition == "promoted" and any(f.blocking for f in findings):
            findings.append(AssuranceEvidenceFinding("PROMOTION_BLOCKED", "promoted evidence has unresolved or invalid authority-critical inputs"))
        if disposition == "promoted":
            if authority_decision is None:
                findings.append(AssuranceEvidenceFinding("MISSING_AUTHORITY_DECISION", "promoted evidence requires supplied authority decision facts"))
            else:
                if authority_decision.get("disposition") != "promoted":
                    findings.append(AssuranceEvidenceFinding("AUTHORITY_DISPOSITION_INVALID", "authority decision does not promote this evidence"))
                if authority_decision.get("evidence_ref") != record["evidence_ref"]:
                    findings.append(AssuranceEvidenceFinding("AUTHORITY_EVIDENCE_MISMATCH", "authority decision names different evidence identity or digest"))
                if authority_decision.get("validity_scope") != record["validity_scope"]:
                    findings.append(AssuranceEvidenceFinding("AUTHORITY_SCOPE_MISMATCH", "authority decision scope differs from lifecycle record"))
                if set(authority_decision.get("supports", ())) != set(record["supports"]):
                    findings.append(AssuranceEvidenceFinding("AUTHORITY_SUPPORT_MISMATCH", "authority decision supports differ from lifecycle record"))
        if disposition == "candidate" and record["authority_decision_ref"] is not None:
            findings.append(AssuranceEvidenceFinding("CANDIDATE_AUTHORITY_CONFLICT", "candidate evidence cannot carry a promotion decision"))
        if disposition != "superseded" and record["supersedes_ref"] is not None:
            findings.append(AssuranceEvidenceFinding("SUPERSESSION_UNEXPECTED", "only superseded evidence may declare supersedes_ref"))

        reproducible = "reproducible" if not any(f.code == "SOURCE_NOT_REPRODUCIBLE" for f in findings) else "non_reproducible"
        if any(f.blocking for f in findings):
            reproducible = "non_reproducible" if reproducible != "reproducible" else "unknown"
        if record["provenance"]["reproducibility"] != reproducible:
            findings.append(AssuranceEvidenceFinding("REPRODUCIBILITY_STATUS_MISMATCH", "declared reproducibility does not match resolved source state"))
        eligible = disposition == "promoted" and not any(f.blocking for f in findings)
        return AssuranceEvidenceValidationResult(True, disposition, reproducible, eligible, tuple(findings))

    @staticmethod
    def _references(record: Mapping[str, Any]) -> tuple[tuple[str, Mapping[str, Any] | None, bool], ...]:
        return (
            ("evidence", record["evidence_ref"], True),
            ("subject", record["subject_ref"], True),
            ("authority decision", record["authority_decision_ref"], record["disposition"] == "promoted"),
            *[("review", ref, record["disposition"] == "promoted") for ref in record["review_refs"]],
            *[("acceptance", ref, record["disposition"] == "promoted") for ref in record["acceptance_refs"]],
            ("superseded evidence", record["supersedes_ref"], record["disposition"] == "superseded"),
        )

    @staticmethod
    def _format_error(error: Any) -> str:
        path = ".".join(str(part) for part in error.absolute_path)
        return f"{path}: {error.message}" if path else error.message
