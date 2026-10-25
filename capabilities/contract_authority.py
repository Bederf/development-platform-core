"""Deterministic validation of contract-authority projections.

This module validates the derived projection shape and reconciles the small
set of authority-critical facts supplied by a caller. It does not discover
providers, authorize actions, execute work, or verify implementations.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
DEFAULT_SCHEMA = ROOT / "contracts" / "contract-authority-projection.v1.schema.json"
DEFAULT_EXCEPTION_SCHEMA = ROOT / "contracts" / "historical-path-identity-exception.v1.schema.json"


@dataclass(frozen=True)
class SourceArtifact:
    """Immutable source snapshot supplied to reconciliation."""

    semantic_type: str
    identifier: str
    version: str
    digest: str
    tracked: bool
    revision: str
    declared_schema_id: str | None = None
    content: bytes | None = None
    declared_status: str | None = None
    path_identity: str | None = None
    artifact_path: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.semantic_type, self.identifier, self.version)


@dataclass(frozen=True)
class PromotionDecision:
    """An accountable authority decision for one exact contract identity."""

    contract_family: str
    contract_version: str
    reference: tuple[str, str, str]
    disposition: str


@dataclass(frozen=True)
class AuthorityFinding:
    reason_code: str
    dimension: str
    source_refs: tuple[tuple[str, str, str], ...] = ()
    detail: str = ""
    blocking: bool = True


@dataclass(frozen=True)
class AuthorityValidationResult:
    structural_valid: bool
    outcome: str
    reproducibility: str
    contract_authoritative: bool
    contract_admissible: bool
    findings: tuple[AuthorityFinding, ...]

    @property
    def valid(self) -> bool:
        return self.structural_valid and self.outcome == "VALID"


class ContractAuthorityValidator:
    """Validate projection structure and reconcile supplied source facts."""

    def __init__(self, schema_path: str | Path | None = None) -> None:
        path = Path(schema_path) if schema_path else DEFAULT_SCHEMA
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)
        exception_schema = json.loads(DEFAULT_EXCEPTION_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(exception_schema)
        self._exception_validator = Draft202012Validator(exception_schema)

    def validate(
        self,
        projection: Mapping[str, Any],
        *,
        sources: Mapping[tuple[str, str, str], SourceArtifact] | None = None,
        promotion_decisions: Sequence[PromotionDecision] = (),
        source_revision: str | None = None,
    ) -> AuthorityValidationResult:
        """Return a deterministic structural and semantic assessment.

        ``sources`` is an explicit snapshot. The validator never reads a
        working tree or invokes Git itself, which keeps source-state authority
        outside this pure validation boundary.
        """

        structural_errors = tuple(
            sorted(self._format_error(error) for error in self._validator.iter_errors(dict(projection)))
        )
        findings: list[AuthorityFinding] = [
            AuthorityFinding("SCHEMA_INVALID", "identity", detail=error)
            for error in structural_errors
        ]
        if structural_errors:
            return AuthorityValidationResult(False, "INVALID", "non_reproducible", False, False, tuple(findings))

        sources = sources or {}
        contract = projection["contract"]
        authority = projection["authority"]
        provenance = projection["provenance"]
        reconciliation = projection["reconciliation"]
        exception_findings, exception_applied = self._check_historical_exception(
            contract, authority, sources, source_revision
        )
        findings.extend(exception_findings)
        findings.extend(self._check_identity(contract, authority, sources, exception_applied))
        findings.extend(self._check_authority(contract, authority, sources, promotion_decisions))
        findings.extend(self._check_source_state(provenance, sources, source_revision))
        findings.extend(self._check_dimensions(projection["status_dimensions"], sources))
        findings.extend(self._check_lifecycle(projection["status_dimensions"]["lifecycle"], sources))
        findings.extend(self._check_references(projection, sources))
        findings.extend(self._check_projection_digest(projection))

        findings = self._stable_findings(findings)
        if exception_applied:
            findings = self._stable_findings(
                [
                    finding
                    for finding in findings
                    if finding.reason_code != "PATH_ID_MISMATCH"
                ]
                + [AuthorityFinding("HISTORICAL_IDENTITY_EXCEPTION_APPLIED", "identity", detail="path/$id mismatch is covered by a valid historical exception", blocking=False)]
            )
        derived_reproducibility = self._derive_reproducibility(findings)
        if projection["provenance"]["reproducibility"]["status"] != derived_reproducibility:
            findings = self._stable_findings(
                [
                    *findings,
                    AuthorityFinding(
                        "SOURCE_NOT_REPRODUCIBLE",
                        "provenance",
                        detail="declared reproducibility does not match resolved source state",
                    ),
                ]
            )
        derived_reasons = {finding.reason_code for finding in findings}
        declared_reasons = set(reconciliation["reason_codes"])
        derived_blocked_reasons = {finding.reason_code for finding in findings if finding.blocking}
        declared_blocked_reasons = set(projection["admissibility"]["blocked_reasons"])
        if declared_reasons != derived_reasons or declared_blocked_reasons != derived_blocked_reasons:
            findings = self._stable_findings(
                [
                    *findings,
                    AuthorityFinding(
                        "STATUS_UNSUPPORTED",
                        "authority",
                        detail="declared reason codes do not match derived findings",
                    ),
                ]
            )
        outcome = self._derive_outcome(findings)
        reproducibility = self._derive_reproducibility(findings)
        authoritative = outcome == "VALID" and authority["disposition"] == "promoted"
        if outcome in {"CONTRADICTORY", "UNRESOLVED", "INVALID"}:
            authoritative = False
        lifecycle_status = projection["status_dimensions"]["lifecycle"]["status"]
        admissible = authoritative and lifecycle_status == "active"

        expected_blocking = outcome != "VALID"
        if reconciliation["outcome"] != outcome:
            findings = self._stable_findings(
                [
                    *findings,
                    AuthorityFinding(
                        "STATUS_UNSUPPORTED",
                        "authority",
                        detail="declared reconciliation outcome does not match derived outcome",
                    ),
                ]
            )
            outcome = "CONTRADICTORY"
            authoritative = False
            admissible = False
        if reconciliation["blocking"] != expected_blocking:
            findings = self._stable_findings(
                [
                    *findings,
                    AuthorityFinding(
                        "STATUS_UNSUPPORTED",
                        "authority",
                        detail="declared blocking flag does not match reconciliation outcome",
                    ),
                ]
            )
            outcome = "CONTRADICTORY"
            authoritative = False
            admissible = False
        if projection["admissibility"]["contract_authoritative"] != authoritative:
            findings = self._stable_findings(
                [
                    *findings,
                    AuthorityFinding(
                        "STATUS_UNSUPPORTED",
                        "authority",
                        detail="declared contract_authoritative does not match derived authority",
                    ),
                ]
            )
            outcome = "CONTRADICTORY"
            authoritative = False
            admissible = False

        return AuthorityValidationResult(
            structural_valid=True,
            outcome=outcome,
            reproducibility=reproducibility,
            contract_authoritative=authoritative,
            contract_admissible=admissible,
            findings=self._stable_findings(findings),
        )

    def _check_identity(
        self,
        contract: Mapping[str, Any],
        authority: Mapping[str, Any],
        sources: Mapping[tuple[str, str, str], SourceArtifact],
        exception_applied: bool = False,
    ) -> list[AuthorityFinding]:
        findings: list[AuthorityFinding] = []
        key = ("contract_schema", contract["schema_id"], contract["version"])
        source = sources.get(key)
        if source is None:
            findings.append(AuthorityFinding("EVIDENCE_MISSING", "identity", (key,), "contract schema snapshot is absent"))
            return findings
        if source.digest != contract["schema_digest"]:
            findings.append(AuthorityFinding("DIGEST_MISMATCH", "identity", (key,), "schema digest differs from source snapshot"))
        if source.declared_schema_id and source.declared_schema_id != contract["schema_id"]:
            findings.append(AuthorityFinding("PATH_ID_MISMATCH", "identity", (key,), "source path identity differs from declared schema id"))
        if source.path_identity and source.path_identity != contract["schema_id"] and not exception_applied:
            findings.append(AuthorityFinding("PATH_ID_MISMATCH", "identity", (key,), "source filename identity differs from contract identity"))
        if source.declared_status in {"candidate", "candidate-only", "pending"}:
            if authority["disposition"] == "promoted":
                findings.append(AuthorityFinding("CANDIDATE_PROMOTION_CONFLICT", "authority", (key,), "candidate source status conflicts with promoted authority"))
        return findings

    def _check_historical_exception(
        self,
        contract: Mapping[str, Any],
        authority: Mapping[str, Any],
        sources: Mapping[tuple[str, str, str], SourceArtifact],
        source_revision: str | None,
    ) -> tuple[list[AuthorityFinding], bool]:
        ref = authority.get("historical_identity_exception_ref")
        if ref is None:
            return [], False
        key = (ref["semantic_type"], ref["id"], ref["version"])
        source = sources.get(key)
        if source is None:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_MISSING", "identity", (key,), "historical exception source is absent")], False
        if not source.tracked:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_UNTRACKED", "provenance", (key,), "historical exception is not reproducible")], False
        if source_revision is not None and source.revision != source_revision:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_REVISION_INVALID", "provenance", (key,), "historical exception revision differs from supplied source revision")], False
        if source.content is None or sha256_digest(source.content) != source.digest or source.digest != ref["digest"]:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_DIGEST_INVALID", "identity", (key,), "historical exception digest is invalid")], False
        try:
            exception = json.loads(source.content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return [AuthorityFinding("HISTORICAL_EXCEPTION_INVALID", "identity", (key,), "historical exception is not valid JSON")], False
        errors = tuple(sorted(self._format_error(error) for error in self._exception_validator.iter_errors(exception)))
        if errors:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_INVALID", "identity", (key,), error) for error in errors], False
        if exception["contract_family"] != contract["family"] or exception["contract_version"] != contract["version"] or exception["schema_id"] != contract["schema_id"]:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_SCOPE_INVALID", "identity", (key,), "exception contract identity does not match projection")], False
        schema_key = ("contract_schema", contract["schema_id"], contract["version"])
        schema_source = sources.get(schema_key)
        if schema_source is None or schema_source.artifact_path != exception["artifact_path"]:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_SCOPE_INVALID", "identity", (key,), "exception artifact path does not match resolved source path")], False
        if schema_source.digest != exception["source_digest"]:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_DIGEST_INVALID", "identity", (key,), "exception source digest does not match contract source")], False
        decision = exception["owner_decision_ref"]
        decision_key = (decision["semantic_type"], decision["id"], decision["version"])
        decision_source = sources.get(decision_key)
        if decision_source is None:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_MISSING", "authority", (decision_key,), "owner decision source is absent")], False
        if not decision_source.tracked:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_UNTRACKED", "authority", (decision_key,), "owner decision is not reproducible")], False
        if decision_source.content is None or sha256_digest(decision_source.content) != decision_source.digest or decision_source.digest != decision["digest"]:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_DIGEST_INVALID", "authority", (decision_key,), "owner decision digest is invalid")], False
        if source.revision != exception["source_revision"] or decision_source.revision != exception["source_revision"]:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_REVISION_INVALID", "provenance", (key, decision_key), "exception evidence is not bound to one source revision")], False
        if not self._is_external_source_revision(exception["source_revision"]):
            return [AuthorityFinding("SOURCE_REVISION_BINDING_INVALID", "provenance", (key,), "source revision is not an external non-self-referential binding")], False
        if exception["exception_status"] == "revoked":
            return [AuthorityFinding("HISTORICAL_EXCEPTION_REVOKED", "identity", (key,), "historical exception is revoked")], False
        if exception["exception_status"] == "expired":
            return [AuthorityFinding("HISTORICAL_EXCEPTION_EXPIRED", "identity", (key,), "historical exception is expired")], False
        if exception["exception_status"] != "active":
            return [AuthorityFinding("HISTORICAL_EXCEPTION_INVALID", "identity", (key,), "historical exception is not active")], False
        if not all(exception["constraints"].values()):
            return [AuthorityFinding("HISTORICAL_EXCEPTION_NON_TRANSFERABLE", "authority", (key,), "exception constraints do not preserve non-authority guarantees")], False
        mismatch = schema_source.path_identity and schema_source.path_identity != contract["schema_id"]
        if not mismatch:
            return [AuthorityFinding("HISTORICAL_EXCEPTION_SCOPE_INVALID", "identity", (key,), "exception does not explain an identity mismatch")], False
        return [], True

    @staticmethod
    def _is_external_source_revision(value: str) -> bool:
        return re.fullmatch(r"git-ref:refs/tags/[A-Za-z0-9][A-Za-z0-9._/-]*", value) is not None

    def _check_authority(
        self,
        contract: Mapping[str, Any],
        authority: Mapping[str, Any],
        sources: Mapping[tuple[str, str, str], SourceArtifact],
        decisions: Sequence[PromotionDecision],
    ) -> list[AuthorityFinding]:
        findings: list[AuthorityFinding] = []
        family = contract["family"]
        version = contract["version"]
        matching = [d for d in decisions if d.contract_family == family and d.contract_version == version]
        if authority["disposition"] == "promoted" and not matching:
            ref = authority["promotion_decision_ref"]
            refs = ((ref["semantic_type"], ref["id"], ref["version"]),) if ref else ()
            findings.append(AuthorityFinding("MISSING_AUTHORITY_DECISION", "authority", refs, "promoted contract has no supplied promotion decision"))
        if len(matching) > 1 and len({(d.disposition, d.reference) for d in matching}) > 1:
            findings.append(AuthorityFinding("MULTIPLE_AUTHORITY_DECISIONS", "authority", tuple(d.reference for d in matching), "incompatible promotion decisions exist for one contract identity"))
        ref = authority["promotion_decision_ref"]
        if matching and ref is not None and all(d.reference != (ref["semantic_type"], ref["id"], ref["version"]) for d in matching):
            findings.append(AuthorityFinding("CANDIDATE_PROMOTION_CONFLICT", "authority", tuple(d.reference for d in matching), "projection promotion reference does not match supplied decision"))
        if matching and authority["disposition"] == "promoted" and any(d.disposition != "promoted" for d in matching):
            findings.append(AuthorityFinding("CANDIDATE_PROMOTION_CONFLICT", "authority", tuple(d.reference for d in matching), "projection claims promoted but supplied decision does not"))
        if ref is not None:
            key = (ref["semantic_type"], ref["id"], ref["version"])
            source = sources.get(key)
            if source is None:
                findings.append(AuthorityFinding("EVIDENCE_MISSING", "authority", (key,), "promotion decision reference is absent"))
            elif not source.tracked:
                findings.append(AuthorityFinding("UNTRACKED_AUTHORITY_SOURCE", "authority", (key,), "promotion decision is not reproducible from tracked source"))
            elif source.digest != ref["digest"]:
                findings.append(AuthorityFinding("DIGEST_MISMATCH", "authority", (key,), "promotion decision digest differs from reference"))
        binding = authority["authority_binding_ref"]
        if authority["disposition"] == "promoted" and binding is None:
            findings.append(AuthorityFinding("AUTHORITY_BINDING_INVALID", "authority", detail="promoted contract has no authority binding"))
        if binding is not None:
            key = (binding["semantic_type"], binding["id"], binding["version"])
            source = sources.get(key)
            if source is None:
                findings.append(AuthorityFinding("AUTHORITY_BINDING_INVALID", "authority", (key,), "authority binding reference is absent"))
            elif not source.tracked:
                findings.append(AuthorityFinding("AUTHORITY_BINDING_INVALID", "authority", (key,), "authority binding is not reproducible"))
            elif source.digest != binding["digest"]:
                findings.append(AuthorityFinding("DIGEST_MISMATCH", "authority", (key,), "authority binding digest differs from reference"))
        return findings

    def _check_source_state(
        self,
        provenance: Mapping[str, Any],
        sources: Mapping[tuple[str, str, str], SourceArtifact],
        source_revision: str | None,
    ) -> list[AuthorityFinding]:
        findings: list[AuthorityFinding] = []
        declared = provenance["source_revision"]
        if source_revision is not None and declared != source_revision:
            findings.append(AuthorityFinding("SOURCE_NOT_REPRODUCIBLE", "provenance", detail="projection revision differs from supplied source revision"))
        if not sources or any(not source.tracked or source.revision != declared or source.content is None for source in sources.values()):
            findings.append(AuthorityFinding("SOURCE_NOT_REPRODUCIBLE", "provenance", detail="authority input is untracked or from another revision"))
        for source in sources.values():
            if source.content is not None and sha256_digest(source.content) != source.digest:
                findings.append(AuthorityFinding("DIGEST_MISMATCH", "provenance", (source.key,), "source digest does not match source content"))
        return findings

    def _check_references(self, projection: Mapping[str, Any], sources: Mapping[tuple[str, str, str], SourceArtifact]) -> list[AuthorityFinding]:
        findings: list[AuthorityFinding] = []
        refs: list[tuple[str, Mapping[str, Any]]] = []
        dimensions = projection["status_dimensions"]
        for name in ("implementation", "conformance", "qualification", "baseline"):
            refs.extend((name, ref) for ref in dimensions[name].get("evidence_refs", []))
        refs.extend(("evidence", item["reference"]) for item in projection["evidence"])
        lifecycle = dimensions["lifecycle"]
        for name in ("supersession_ref", "deprecation_ref"):
            if lifecycle[name] is not None:
                refs.append(("lifecycle", lifecycle[name]))
        for dimension, ref in refs:
            key = (ref["semantic_type"], ref["id"], ref["version"])
            source = sources.get(key)
            if source is None:
                findings.append(AuthorityFinding("EVIDENCE_MISSING", dimension, (key,), "referenced evidence is absent"))
            elif not source.tracked:
                findings.append(AuthorityFinding("UNTRACKED_AUTHORITY_SOURCE", dimension, (key,), "referenced evidence is not reproducible"))
            elif source.digest != ref["digest"]:
                findings.append(AuthorityFinding("EVIDENCE_DIGEST_INVALID", dimension, (key,), "referenced evidence digest differs from source"))
            elif not self._evidence_type_matches(dimension, source.semantic_type):
                findings.append(AuthorityFinding("STATUS_UNSUPPORTED", dimension, (key,), "evidence semantic type does not support the claimed dimension"))
        expected_digests = {source.digest for source in sources.values()}
        declared_digests = set(projection["provenance"]["source_digests"])
        if expected_digests != declared_digests:
            findings.append(AuthorityFinding("EVIDENCE_DIGEST_INVALID", "provenance", detail="declared source digest set differs from resolved source set"))
        return findings

    @staticmethod
    def _evidence_type_matches(dimension: str, semantic_type: str) -> bool:
        aliases = {
            "implementation": {"implementation_evidence", "implementation"},
            "conformance": {"conformance_evidence", "conformance"},
            "qualification": {"qualification_evidence", "qualification"},
            "baseline": {"freeze_record", "baseline", "contract_freeze"},
            "lifecycle": {"lifecycle", "supersession", "deprecation"},
            "evidence": {"evidence", "authority_evidence", "promotion_record", "review_evidence", "qualification_evidence"},
        }
        return semantic_type in aliases.get(dimension, {semantic_type})

    def _check_projection_digest(self, projection: Mapping[str, Any]) -> list[AuthorityFinding]:
        expected = projection["provenance"]["projection_digest"]
        material = json.loads(json.dumps(projection))
        material["provenance"].pop("projection_digest", None)
        actual = sha256_digest(json.dumps(material, sort_keys=True, separators=(",", ":")).encode())
        if expected != actual:
            return [AuthorityFinding("DIGEST_MISMATCH", "provenance", detail="projection digest does not match canonical projection")]
        return []

    def _check_dimensions(
        self,
        dimensions: Mapping[str, Any],
        sources: Mapping[tuple[str, str, str], SourceArtifact],
    ) -> list[AuthorityFinding]:
        findings: list[AuthorityFinding] = []
        for dimension_name in ("implementation", "conformance", "qualification"):
            dimension = dimensions[dimension_name]
            if dimension["status"] not in {"absent", "not_assessed", "unknown"} and not dimension["evidence_refs"]:
                findings.append(AuthorityFinding("EVIDENCE_MISSING", dimension_name, detail="positive status has no evidence reference"))
        return findings

    def _check_lifecycle(self, lifecycle: Mapping[str, Any], sources: Mapping[tuple[str, str, str], SourceArtifact]) -> list[AuthorityFinding]:
        findings: list[AuthorityFinding] = []
        if lifecycle["status"] in {"deprecated", "withdrawn", "superseded"} and lifecycle["supersession_ref"] is None and lifecycle["deprecation_ref"] is None:
            findings.append(AuthorityFinding("SUPERSESSION_CONFLICT", "lifecycle", detail="retired lifecycle status has no supporting lifecycle reference"))
        return findings

    @staticmethod
    def _derive_outcome(findings: Sequence[AuthorityFinding]) -> str:
        unresolved_exception = {
            "HISTORICAL_EXCEPTION_MISSING",
            "HISTORICAL_EXCEPTION_UNTRACKED",
            "HISTORICAL_EXCEPTION_REVISION_INVALID",
        }
        invalid_reasons = {
            "IDENTITY_MISMATCH", "VERSION_MISMATCH", "DIGEST_MISMATCH",
            "EVIDENCE_DIGEST_INVALID", "AUTHORITY_BINDING_INVALID",
            "STATUS_UNSUPPORTED", "HISTORICAL_EXCEPTION_INVALID",
            "HISTORICAL_EXCEPTION_DIGEST_INVALID",
            "HISTORICAL_EXCEPTION_SCOPE_INVALID",
            "HISTORICAL_EXCEPTION_EXPIRED", "HISTORICAL_EXCEPTION_REVOKED",
            "HISTORICAL_EXCEPTION_NON_TRANSFERABLE",
        }
        codes = {finding.reason_code for finding in findings}
        if codes & unresolved_exception and not codes & invalid_reasons:
            return "UNRESOLVED"
        if any(f.reason_code in {"IDENTITY_MISMATCH", "VERSION_MISMATCH", "DIGEST_MISMATCH", "EVIDENCE_DIGEST_INVALID", "PATH_ID_MISMATCH", "AUTHORITY_BINDING_INVALID", "STATUS_UNSUPPORTED", "HISTORICAL_EXCEPTION_INVALID", "HISTORICAL_EXCEPTION_DIGEST_INVALID", "HISTORICAL_EXCEPTION_REVISION_INVALID", "HISTORICAL_EXCEPTION_SCOPE_INVALID", "HISTORICAL_EXCEPTION_EXPIRED", "HISTORICAL_EXCEPTION_REVOKED", "HISTORICAL_EXCEPTION_NON_TRANSFERABLE", "SOURCE_REVISION_BINDING_INVALID"} for f in findings):
            return "INVALID"
        if any(f.reason_code in {"MULTIPLE_AUTHORITY_DECISIONS", "CANDIDATE_PROMOTION_CONFLICT", "FREEZE_SCOPE_CONFLICT", "SUPERSESSION_CONFLICT", "DEPRECATION_CONFLICT", "HISTORICAL_EXCEPTION_CONFLICT"} for f in findings):
            return "CONTRADICTORY"
        if any(f.reason_code != "HISTORICAL_IDENTITY_EXCEPTION_APPLIED" for f in findings):
            return "UNRESOLVED"
        return "VALID"

    @staticmethod
    def _derive_reproducibility(findings: Sequence[AuthorityFinding]) -> str:
        return "non_reproducible" if any(f.reason_code in {"SOURCE_NOT_REPRODUCIBLE", "UNTRACKED_AUTHORITY_SOURCE"} for f in findings) else "reproducible"

    @staticmethod
    def _stable_findings(findings: Sequence[AuthorityFinding]) -> tuple[AuthorityFinding, ...]:
        return tuple(sorted(set(findings), key=lambda f: (f.dimension, f.reason_code, f.detail, f.source_refs)))

    @staticmethod
    def _format_error(error: Any) -> str:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        return f"{path}: {error.message}"


def sha256_digest(payload: bytes) -> str:
    """Return the repository digest representation used by authority inputs."""

    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
