"""Core-owned persistence authority for ``development-workflow.v1``.

Providers and consumers may prepare evidence, but only this boundary can
persist an ACCEPTED workflow record.  The authority is deliberately small: it
composes the existing requirement and completion gates and the existing
provider-neutral convergence adapter.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .completion_gate import assess_completion
from .phase_authorization import (
    FileAuthorizationStore,
    PhaseAuthorizationError,
    resolve_authorization,
)
from .phase_specification import SpecificationResolution, validate_phase_specification
from .review_requirements import assess_requirements


class AcceptanceAuthorityError(ValueError):
    """Raised when an acceptance attempt cannot be authorized."""


class AcceptanceConflict(AcceptanceAuthorityError):
    """Raised when an existing acceptance belongs to another attempt."""


def _canonical_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("digest", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_phase_binding(
    binding: Mapping[str, Any],
    *,
    approved_specification_ref: str,
    resolution: SpecificationResolution,
    authoritative_specification: Mapping[str, Any],
    forge_required: bool | None,
    verification_mode: str | None,
) -> tuple[bool, str]:
    required = {
        "phase_id",
        "specification_ref",
        "specification_id",
        "specification_version",
        "specification_hash",
        "forge_required",
        "verification_mode",
    }
    missing = sorted(required - set(binding))
    if missing:
        raise AcceptanceAuthorityError(
            f"phase specification binding is incomplete: {', '.join(missing)}"
        )
    if binding["specification_ref"] != approved_specification_ref:
        raise AcceptanceAuthorityError(
            "phase specification binding references another specification"
        )
    expected_identity = {
        "phase_id": resolution.phase_id,
        "specification_id": resolution.specification_id,
        "specification_version": resolution.version,
        "specification_hash": resolution.specification_hash,
    }
    for field, expected in expected_identity.items():
        if binding[field] != expected:
            raise AcceptanceAuthorityError(
                f"phase specification binding {field} does not match the authoritative specification"
            )
    verification = authoritative_specification["verification"]
    derived_forge_required = verification["forge_required"]
    derived_mode = (
        "live" if verification["live_verification_required"] else "qualification"
    )
    if forge_required is not None and forge_required != derived_forge_required:
        raise AcceptanceAuthorityError(
            "caller forge_required does not match the approved phase specification"
        )
    if verification_mode is not None and verification_mode != derived_mode:
        raise AcceptanceAuthorityError(
            "caller verification mode does not match the approved phase specification"
        )
    return derived_forge_required, derived_mode


def _resolve_authoritative_specification(
    specification_ref: str,
) -> tuple[Mapping[str, Any], SpecificationResolution]:
    root = Path(__file__).parents[1] / "00-GSD-Phases"
    matches: list[tuple[Mapping[str, Any], SpecificationResolution]] = []
    for path in sorted(root.glob("*.specification.json")):
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            resolution = validate_phase_specification(candidate)
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError):
            continue
        if resolution.specification_id == specification_ref:
            matches.append((candidate, resolution))
    if len(matches) != 1:
        raise AcceptanceAuthorityError(
            "approved phase specification is not uniquely resolvable from Core authority"
        )
    return matches[0]


def _validate_typed_evidence_refs(
    refs: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, Mapping):
            raise AcceptanceAuthorityError("evidence references must be typed objects")
        required = {"semantic_type", "id", "version", "digest"}
        if (
            not required.issubset(ref)
            or not isinstance(ref["digest"], str)
            or "content" not in ref
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", ref["digest"])
        ):
            raise AcceptanceAuthorityError(
                "evidence references must contain typed immutable digests"
            )
        identifier = str(ref["id"])
        if identifier in indexed:
            raise AcceptanceAuthorityError("evidence references contain duplicate ids")
        if _canonical_digest({"content": ref["content"]}) != ref["digest"]:
            raise AcceptanceAuthorityError(
                "evidence reference digest does not match referenced content"
            )
        indexed[identifier] = dict(ref)
    if not indexed:
        raise AcceptanceAuthorityError("typed evidence references are required")
    return indexed


def _validate_forge_evidence(
    evidence: Mapping[str, Any],
    *,
    approved_specification_ref: str,
    expected_status: str,
    expected_source_revision: str,
    acceptance_attempt_id: str,
    expected_review_request_ref: str,
    typed_refs: Mapping[str, Mapping[str, Any]],
) -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "forge-qualification-evidence.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            dict(evidence)
        ),
        key=lambda error: list(error.path),
    )
    if errors:
        raise AcceptanceAuthorityError(
            f"Forge evidence is invalid: {errors[0].message}"
        )
    if evidence["phase_specification_ref"] != approved_specification_ref:
        raise AcceptanceAuthorityError(
            "Forge evidence is bound to another phase specification"
        )
    if evidence["source_revision"] != expected_source_revision:
        raise AcceptanceAuthorityError(
            "Forge evidence source revision is not the accepted implementation revision"
        )
    if evidence["status"] != expected_status or evidence["completeness"] != "COMPLETE":
        raise AcceptanceAuthorityError("Forge evidence is not complete and passed")
    if evidence["verification_attempt_id"] != acceptance_attempt_id:
        raise AcceptanceAuthorityError(
            "Forge evidence verification attempt is not bound to acceptance attempt"
        )
    provenance = evidence["provenance"]
    review_ref = provenance["review_request_ref"]
    if review_ref != expected_review_request_ref:
        raise AcceptanceAuthorityError(
            "Forge evidence review request does not match authorization lineage"
        )
    if not provenance["independence"] or review_ref not in typed_refs:
        raise AcceptanceAuthorityError(
            "Forge evidence is not bound to an independent Core review request"
        )
    if typed_refs[review_ref]["semantic_type"] != "independent-review-request":
        raise AcceptanceAuthorityError(
            "Forge evidence review request reference has the wrong semantic type"
        )
    for ref in evidence["lineage"]:
        if ref["id"] not in typed_refs or typed_refs[ref["id"]] != ref:
            raise AcceptanceAuthorityError(
                "Forge evidence lineage is not bound to typed evidence"
            )
    for check in evidence["checks"]:
        if check["status"] != "PASSED":
            raise AcceptanceAuthorityError(
                "Forge evidence contains a non-passing check"
            )
        for ref in check["evidence_refs"]:
            if ref["id"] not in typed_refs or typed_refs[ref["id"]] != ref:
                raise AcceptanceAuthorityError(
                    "Forge check evidence is not bound to typed evidence"
                )
    for artifact in evidence["artifacts"]:
        if artifact["source_revision"] != expected_source_revision:
            raise AcceptanceAuthorityError(
                "Forge artifact source revision is not bound"
            )
        if _canonical_digest({"content": artifact["content"]}) != artifact["digest"]:
            raise AcceptanceAuthorityError(
                "Forge artifact digest does not match referenced content"
            )
    if _canonical_digest(evidence) != evidence["digest"]:
        raise AcceptanceAuthorityError(
            "Forge evidence digest does not match canonical content"
        )


class AcceptanceAuthority:
    """Persist one idempotent, Core-authorized ACCEPTED workflow record."""

    def __init__(
        self,
        path: str | Path,
        *,
        authorization_store: FileAuthorizationStore | None = None,
    ):
        self.path = Path(path)
        self.authorization_store = authorization_store

    def accept(
        self,
        workflow: Mapping[str, Any],
        *,
        approved_specification_ref: str,
        implementation_revision_ref: str,
        approved_requirement_refs: Iterable[str],
        requirement_evaluations: Iterable[Mapping[str, Any]],
        available_evidence: Iterable[str],
        review_cycle: Mapping[str, Any],
        independent_review_result: Mapping[str, Any],
        focused_tests_passed: bool,
        live_verification_passed: bool,
        evidence_integrity_verified: bool,
        before_after_evidence_present: bool,
        unresolved_blockers: int,
        forge_status: str,
        forge_required: bool | None = None,
        authorization_ref: str | None = None,
        phase_specification_binding: Mapping[str, Any] | None = None,
        verification_mode: str | None = None,
        qualification_evidence_passed: bool = False,
        forge_evidence: Mapping[str, Any] | None = None,
        typed_evidence_refs: Iterable[Mapping[str, Any]] | None = None,
        convergence_result: Mapping[str, Any],
        acceptance_attempt_id: str,
        acceptance_ref: str,
    ) -> dict[str, Any]:
        record = dict(workflow)
        self._validate_workflow(record)
        existing = self._load_existing()
        if existing is not None:
            if (
                existing.get("status") == "ACCEPTED"
                and existing.get("acceptance_ref") == acceptance_ref
            ):
                return existing
            if existing.get("status") == "ACCEPTED" or existing.get("acceptance_ref"):
                raise AcceptanceConflict(
                    "workflow already accepted or has a conflicting persisted acceptance"
                )
        self._require_identity(
            record,
            approved_specification_ref,
            implementation_revision_ref,
            independent_review_result,
            acceptance_attempt_id,
            acceptance_ref,
        )
        if phase_specification_binding is None:
            raise AcceptanceAuthorityError("phase specification binding is required")
        if not authorization_ref:
            raise AcceptanceAuthorityError("Core authorization reference is required")
        authoritative_specification, resolution = _resolve_authoritative_specification(
            approved_specification_ref
        )
        derived_forge_required, derived_verification_mode = _validate_phase_binding(
            phase_specification_binding,
            approved_specification_ref=approved_specification_ref,
            resolution=resolution,
            authoritative_specification=authoritative_specification,
            forge_required=forge_required,
            verification_mode=verification_mode,
        )
        subject = {
            "phase_id": resolution.phase_id,
            "specification_id": resolution.specification_id,
            "specification_version": resolution.version,
            "specification_hash": resolution.specification_hash,
        }
        try:
            authorization = resolve_authorization(
                authorization_ref, subject=subject, store=self.authorization_store
            )
        except PhaseAuthorizationError as exc:
            raise AcceptanceAuthorityError(str(exc)) from exc
        expected_binding = {
            **subject,
            "specification_ref": approved_specification_ref,
            "forge_required": derived_forge_required,
            "verification_mode": derived_verification_mode,
        }
        if dict(phase_specification_binding) != expected_binding:
            raise AcceptanceAuthorityError(
                "phase specification binding is not consistent with resolved authorization"
            )
        specification_artifact = next(
            (
                item
                for item in record.get("artifacts", [])
                if item.get("artifact_ref") == approved_specification_ref
            ),
            None,
        )
        if (
            specification_artifact is None
            or specification_artifact.get("digest")
            != phase_specification_binding["specification_hash"]
        ):
            raise AcceptanceAuthorityError(
                "phase specification binding digest does not match the workflow artifact"
            )
        typed_refs = _validate_typed_evidence_refs(typed_evidence_refs or [])
        if derived_forge_required:
            if forge_status != "PASSED" or forge_evidence is None:
                raise AcceptanceAuthorityError(
                    "Forge evidence is required for the approved phase specification"
                )
            _validate_forge_evidence(
                forge_evidence,
                approved_specification_ref=approved_specification_ref,
                expected_status=forge_status,
                expected_source_revision=implementation_revision_ref,
                acceptance_attempt_id=acceptance_attempt_id,
                expected_review_request_ref=authorization["review_request_ref"]["id"],
                typed_refs=typed_refs,
            )

        requirement_decision = assess_requirements(
            requirement_evaluations,
            mandatory_requirement_refs=approved_requirement_refs,
            available_evidence=available_evidence,
            unresolved_blockers=unresolved_blockers,
        )
        if not requirement_decision.eligible:
            raise AcceptanceAuthorityError(
                f"requirements are not closed: {requirement_decision.reason}; "
                f"unresolved={list(requirement_decision.unresolved_refs)}"
            )

        completion = assess_completion(
            review_cycle,
            requirements_satisfied=True,
            independent_review_result=independent_review_result,
            focused_tests_passed=focused_tests_passed,
            live_verification_passed=live_verification_passed,
            evidence_integrity_verified=evidence_integrity_verified,
            before_after_evidence_present=before_after_evidence_present,
            unresolved_blockers=unresolved_blockers,
            forge_status=forge_status,
            forge_required=derived_forge_required,
            verification_mode=derived_verification_mode,
            qualification_evidence_passed=qualification_evidence_passed,
            independent_review_required=bool(
                authoritative_specification.get("independent_review", {}).get("required", True)
            ),
        )
        if not completion.eligible:
            raise AcceptanceAuthorityError(
                f"completion gate rejected acceptance: {completion.reason}"
            )

        if not isinstance(convergence_result, Mapping):
            raise AcceptanceAuthorityError("convergence result is missing")
        if convergence_result.get("report_type") != "convergence":
            raise AcceptanceAuthorityError(
                "convergence did not establish a complete result"
            )
        if convergence_result.get("requirements_complete") is not True:
            raise AcceptanceAuthorityError("convergence requires remediation")
        convergence_refs = [
            str(ref).strip()
            for ref in convergence_result.get("evidence_refs", [])
            if str(ref).strip()
        ]
        if not convergence_refs:
            raise AcceptanceAuthorityError("convergence requires evidence references")

        now = datetime.now(UTC).isoformat()
        acceptance_payload = {
            "schema": "acceptance-content.v1",
            "acceptance_ref": acceptance_ref,
            "artifact_ref": acceptance_ref,
            "kind": "acceptance",
            "stage": "ACCEPTANCE",
            "artifact_version": "1.0.0",
            "producer": "development-platform-core.acceptance-authority",
            "supersedes_ref": None,
            "created_at": now,
            "phase_specification": dict(phase_specification_binding),
            "authorization_ref": authorization_ref,
            "authorization_digest": authorization["digest"],
            "review_request_ref": authorization["review_request_ref"]["id"],
            "implementation_revision_ref": implementation_revision_ref,
            "forge_evidence_ref": forge_evidence["verification_attempt_id"]
            if forge_evidence is not None
            else "not-applicable",
            "forge_evidence_digest": forge_evidence["digest"]
            if forge_evidence is not None
            else None,
            "convergence_refs": convergence_refs,
            "authority_boundary": {
                "forge_non_authoritative": True,
                "production_authority_granted": False,
            },
        }
        acceptance_artifact = {
            **acceptance_payload,
            "digest": _canonical_digest(acceptance_payload),
        }
        acceptance_artifact = {
            key: acceptance_artifact[key]
            for key in (
                "artifact_ref",
                "kind",
                "stage",
                "artifact_version",
                "digest",
                "producer",
                "supersedes_ref",
                "created_at",
            )
        }
        record["acceptance_content"] = acceptance_payload
        record["artifacts"] = [*record.get("artifacts", []), acceptance_artifact]
        record["gates"] = [
            *record.get("gates", []),
            {
                "gate_id": f"acceptance-gate:{acceptance_attempt_id}",
                "stage": "ACCEPTANCE",
                "decision": "APPROVED",
                "decided_by": "development-platform-core.acceptance-authority",
                "evidence_refs": [*convergence_refs, acceptance_ref],
                "decided_at": now,
            },
        ]
        record["transitions"] = [
            *record.get("transitions", []),
            {
                "transition_id": f"acceptance-transition:{acceptance_attempt_id}",
                "from_stage": "CONVERGENCE",
                "to_stage": "ACCEPTANCE",
                "actor": "development-platform-core.acceptance-authority",
                "decision": "ADVANCE",
                "evidence_refs": [*convergence_refs, acceptance_ref],
                "occurred_at": now,
            },
        ]
        record["verification_refs"] = list(
            dict.fromkeys(record.get("verification_refs", []))
        )
        record["evidence_refs"] = list(
            dict.fromkeys(
                [*record.get("evidence_refs", []), *convergence_refs, acceptance_ref]
            )
        )
        record["acceptance_ref"] = acceptance_ref
        record["authorization_ref"] = authorization_ref
        record["authorization_digest"] = authorization["digest"]
        record["current_stage"] = "ACCEPTANCE"
        record["status"] = "ACCEPTED"
        record["updated_at"] = now
        self._validate_workflow(record)
        self._atomic_write(record)
        return record

    def _load_existing(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AcceptanceAuthorityError("persisted workflow is unreadable") from exc
        if not isinstance(value, dict):
            raise AcceptanceAuthorityError("persisted workflow must be an object")
        self._validate_workflow(value)
        return value

    @staticmethod
    def _require_identity(
        record: Mapping[str, Any],
        specification_ref: str,
        implementation_ref: str,
        review: Mapping[str, Any],
        attempt_id: str,
        acceptance_ref: str,
    ) -> None:
        artifact_refs = {
            str(item.get("artifact_ref")) for item in record.get("artifacts", [])
        }
        if (
            not isinstance(specification_ref, str)
            or specification_ref not in artifact_refs
        ):
            raise AcceptanceAuthorityError(
                "approved specification is not part of this workflow"
            )
        if (
            not isinstance(implementation_ref, str)
            or implementation_ref not in artifact_refs
        ):
            raise AcceptanceAuthorityError(
                "implementation revision is not part of this workflow"
            )
        if (
            not isinstance(review, Mapping)
            or review.get("attempt_ref") != implementation_ref
        ):
            raise AcceptanceAuthorityError(
                "independent review is bound to another implementation revision"
            )
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise AcceptanceAuthorityError("acceptance_attempt_id is required")
        if not isinstance(acceptance_ref, str) or not acceptance_ref.strip():
            raise AcceptanceAuthorityError("acceptance_ref is required")
        if record.get("status") == "ACCEPTED":
            raise AcceptanceAuthorityError(
                "an already accepted workflow cannot be downgraded"
            )
        if record.get("current_stage") != "CONVERGENCE":
            raise AcceptanceAuthorityError(
                "acceptance requires the workflow to be at CONVERGENCE"
            )

    @staticmethod
    def _validate_workflow(record: Mapping[str, Any]) -> None:
        schema_path = (
            Path(__file__).parents[1]
            / "contracts"
            / "development-workflow.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        acceptance_schema = json.loads(
            (schema_path.parent / "acceptance-content.v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        schema["properties"]["acceptance_content"] = {
            "anyOf": [acceptance_schema, {"type": "null"}]
        }
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                dict(record)
            ),
            key=lambda error: list(error.path),
        )
        if errors:
            raise AcceptanceAuthorityError(
                f"invalid development workflow: {errors[0].message}"
            )
        if record.get("status") == "ACCEPTED":
            content = record.get("acceptance_content")
            acceptance_artifacts = [
                item
                for item in record.get("artifacts", [])
                if item.get("kind") == "acceptance"
            ]
            if not isinstance(content, Mapping) or len(acceptance_artifacts) != 1:
                raise AcceptanceAuthorityError(
                    "accepted workflow does not retain exactly one acceptance content artifact"
                )
            if content.get("acceptance_ref") != record.get("acceptance_ref"):
                raise AcceptanceAuthorityError(
                    "acceptance content is bound to another acceptance reference"
                )
            if content.get("authorization_ref") != record.get(
                "authorization_ref"
            ) or content.get("authorization_digest") != record.get(
                "authorization_digest"
            ):
                raise AcceptanceAuthorityError(
                    "acceptance content authorization lineage does not match workflow"
                )
            if _canonical_digest(content) != acceptance_artifacts[0].get("digest"):
                raise AcceptanceAuthorityError(
                    "persisted acceptance content digest does not match its artifact"
                )

    def _atomic_write(self, record: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
