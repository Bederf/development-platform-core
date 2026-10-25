"""Core-owned resolution and validation for bounded phase authorization."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


EXPECTED_PHASE034_SPECIFICATION_HASH = (
    "sha256:64cbf8307f298b401fc8595e23895912b33bebaa3f10649bd349df67951756e4"
)

V1_AUTHORIZATION_SCHEMA = "core-qualification-authorization.v1"
V2_AUTHORIZATION_SCHEMA = "core-qualification-authorization.v2"
PROFILE_SCHEMA = "core-qualification-profile.v1"


class PhaseAuthorizationError(ValueError):
    """Raised when a phase authorization cannot be trusted."""


def canonical_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("digest", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class FileAuthorizationStore:
    """Resolve authorization records from a Core-owned source and index."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        index_path: str | Path | None = None,
        lineage_records: Mapping[str, Mapping[str, Any]] | None = None,
        test_only: bool = False,
        root: str | Path | None = None,
    ):
        if root is not None and not test_only:
            raise PhaseAuthorizationError("custom authorization roots are test-only")
        self.root = Path(root).resolve() if root is not None else Path(__file__).parents[1]
        if not test_only and (
            path is not None or index_path is not None or lineage_records
        ):
            raise PhaseAuthorizationError("custom authorization sources are test-only")
        self.path = Path(path) if path is not None else None
        self.index_path = Path(index_path) if index_path is not None else None
        self.lineage_records = dict(lineage_records or {})
        self.test_only = test_only

    def _index(self) -> dict[str, Any]:
        path = (
            self.index_path
            or self.root / "docs" / "assurance" / "CORE-AUTHORIZATION-INDEX-v1.json"
        )
        try:
            index = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PhaseAuthorizationError(
                "Core authorization index is unavailable"
            ) from exc
        if canonical_digest(index) != index.get("digest"):
            raise PhaseAuthorizationError("Core authorization index digest is invalid")
        return index

    def _resolve_indexed_ref(self, ref: Mapping[str, Any]) -> dict[str, Any]:
        entries = self._index().get("entries")
        if not isinstance(entries, list):
            raise PhaseAuthorizationError("Core authorization index entries are invalid")
        matches = [
            item for item in entries
            if isinstance(item, Mapping) and item.get("id") == ref.get("id")
        ]
        if len(matches) != 1:
            raise PhaseAuthorizationError("authorization reference is missing or ambiguous")
        entry = matches[0]
        if not isinstance(entry.get("digest"), str) or entry["digest"] != ref.get("digest"):
            raise PhaseAuthorizationError(
                "authorization lineage reference is missing or altered"
            )
        relative_path = entry.get("path")
        if not isinstance(relative_path, str):
            raise PhaseAuthorizationError("authorization lineage path is invalid")
        lexical_path = self.root / relative_path
        if lexical_path.is_symlink() or not lexical_path.is_file():
            raise PhaseAuthorizationError("authorization lineage artifact is unavailable")
        path = lexical_path.resolve()
        if not self.test_only:
            try:
                path.relative_to(self.root)
            except ValueError as exc:
                raise PhaseAuthorizationError("authorization lineage path escapes Core") from exc
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PhaseAuthorizationError(
                "authorization lineage artifact is unavailable"
            ) from exc
        if canonical_digest(value) != entry["digest"]:
            raise PhaseAuthorizationError(
                "authorization lineage artifact digest is invalid"
            )
        if "digest" in value and canonical_digest(value) != value.get("digest"):
            raise PhaseAuthorizationError(
                "authorization lineage artifact self-digest is invalid"
            )
        return value

    def resolve_phase_specification_binding(
        self,
        binding_id: str,
        *,
        subject: Mapping[str, Any],
        authority_binding_id: str = "core-phase-authority",
    ) -> dict[str, Any]:
        """Resolve an approved phase subject through the Core authority index."""

        index = self._index()
        entries = index.get("entries")
        if not isinstance(entries, list):
            raise PhaseAuthorizationError("Core authorization index entries are invalid")
        matches = [
            item for item in entries
            if isinstance(item, Mapping) and item.get("id") == binding_id
        ]
        if len(matches) != 1:
            raise PhaseAuthorizationError(
                "phase specification binding is missing or ambiguous"
            )
        entry = matches[0]
        record = self._resolve_indexed_ref(entry)
        if (
            record.get("schema") != "core-phase-specification-binding.v1"
            or record.get("binding_id") != binding_id
            or record.get("version") != "1.0.0"
            or record.get("decision") != "approved"
            or record.get("issuer") != "development-platform-core.phase-authority"
            or record.get("subject") != dict(subject)
        ):
            raise PhaseAuthorizationError(
                "phase specification binding is invalid or does not match the subject"
            )
        authority = record.get("authority_binding")
        if not isinstance(authority, Mapping):
            raise PhaseAuthorizationError("phase specification authority binding is missing")
        if authority.get("id") != authority_binding_id:
            raise PhaseAuthorizationError("phase specification authority binding is not Core-owned")
        authority_matches = [
            item for item in entries
            if isinstance(item, Mapping) and item.get("id") == authority_binding_id
        ]
        if len(authority_matches) != 1:
            raise PhaseAuthorizationError("Core authority binding is missing or ambiguous")
        if authority_matches[0].get("digest") != authority.get("digest"):
            raise PhaseAuthorizationError("Core authority binding digest is not indexed")
        authority_record = self._resolve_indexed_ref(authority)
        if authority_record.get("binding_id") != authority_binding_id:
            raise PhaseAuthorizationError("Core authority binding identity is invalid")
        return record

    def resolve_project_phase_specification_binding(
        self,
        binding_id: str,
        *,
        subject: Mapping[str, Any],
        authority_binding_id: str = "core-phase-authority",
    ) -> dict[str, Any]:
        """Resolve one project-local phase through the Core authority index.

        The project phase remains outside the Core phase namespace. Core stores
        only the subject-bound authority record and its digest; the caller must
        resolve and verify the project artifact in the project repository.
        """

        index = self._index()
        entries = index.get("entries")
        if not isinstance(entries, list):
            raise PhaseAuthorizationError("Core authorization index entries are invalid")
        matches = [
            item for item in entries
            if isinstance(item, Mapping) and item.get("id") == binding_id
        ]
        if len(matches) != 1:
            raise PhaseAuthorizationError(
                "project phase specification binding is missing or ambiguous"
            )
        entry = matches[0]
        record = self._resolve_indexed_ref(entry)
        if (
            record.get("schema") != "core-project-phase-specification-binding.v1"
            or record.get("binding_id") != binding_id
            or record.get("version") != "1.0.0"
            or record.get("decision") != "approved"
            or record.get("issuer") != "development-platform-core.phase-authority"
            or record.get("subject") != dict(subject)
        ):
            raise PhaseAuthorizationError(
                "project phase binding is invalid or does not match the subject"
            )
        scope = record.get("scope")
        if not isinstance(scope, Mapping) or scope.get("scope_type") != "project_consumer_phase":
            raise PhaseAuthorizationError("project phase binding scope is invalid")
        excluded = scope.get("excluded_authorities")
        required_exclusions = {
            "implementation",
            "consumer_activation",
            "deployment",
            "production_authority",
            "physical_control",
        }
        if not isinstance(excluded, list) or not required_exclusions.issubset(excluded):
            raise PhaseAuthorizationError(
                "project phase binding does not preserve required authority exclusions"
            )
        authority = record.get("authority_binding")
        if not isinstance(authority, Mapping):
            raise PhaseAuthorizationError("project phase authority binding is missing")
        if authority.get("id") != authority_binding_id:
            raise PhaseAuthorizationError("project phase authority binding is not Core-owned")
        authority_matches = [
            item for item in entries
            if isinstance(item, Mapping) and item.get("id") == authority_binding_id
        ]
        if len(authority_matches) != 1:
            raise PhaseAuthorizationError("Core authority binding is missing or ambiguous")
        if authority_matches[0].get("digest") != authority.get("digest"):
            raise PhaseAuthorizationError("Core authority binding digest is not indexed")
        authority_record = self._resolve_indexed_ref(authority)
        if authority_record.get("binding_id") != authority_binding_id:
            raise PhaseAuthorizationError("Core authority binding identity is invalid")
        return record

    def resolve(self, authorization_ref: str) -> dict[str, Any]:
        if self.path is None:
            index = self._index()
            entry = next(
                (item for item in index["entries"] if item["id"] == authorization_ref),
                None,
            )
            if entry is None:
                raise PhaseAuthorizationError("authorization record is missing")
            record = self._resolve_indexed_ref(entry)
        else:
            try:
                record = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PhaseAuthorizationError(
                    "authorization record is unavailable"
                ) from exc
        if (
            not isinstance(record, dict)
            or record.get("authorization_id") != authorization_ref
        ):
            raise PhaseAuthorizationError("authorization record is missing")
        schema_name = record.get("schema")
        schema_file = {
            V1_AUTHORIZATION_SCHEMA: "core-qualification-authorization.v1.schema.json",
            V2_AUTHORIZATION_SCHEMA: "core-qualification-authorization.v2.schema.json",
        }.get(schema_name)
        if schema_file is None:
            raise PhaseAuthorizationError("authorization schema version is unsupported")
        schema = json.loads((self.root / "contracts" / schema_file).read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                record
            ),
            key=lambda error: list(error.path),
        )
        if errors:
            raise PhaseAuthorizationError(
                f"authorization record is invalid: {errors[0].message}"
            )
        if canonical_digest(record) != record["digest"]:
            raise PhaseAuthorizationError("authorization digest is invalid")
        refs = [record["authority_binding"], record["review_request_ref"], *record["lineage"]]
        if schema_name == V2_AUTHORIZATION_SCHEMA:
            refs.append(record["profile_ref"])
            refs.append(record["owner_approval_ref"])
        for ref in refs:
            if ref["semantic_type"] == "phase-specification":
                continue
            if ref["id"] in self.lineage_records:
                if canonical_digest(self.lineage_records[ref["id"]]) != ref["digest"]:
                    raise PhaseAuthorizationError(
                        "injected authorization lineage digest is invalid"
                    )
            elif self.path is None:
                self._resolve_indexed_ref(ref)
            else:
                raise PhaseAuthorizationError("authorization lineage is not resolvable")
        return record

    def resolve_profile(self, profile_ref: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve one immutable, Core-governed qualification profile."""

        if profile_ref.get("semantic_type") != "qualification-profile":
            raise PhaseAuthorizationError("authorization profile reference has the wrong semantic type")
        profile = self._resolve_indexed_ref(profile_ref)
        schema = json.loads(
            (self.root / "contracts" / "core-qualification-profile.v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(profile),
            key=lambda error: list(error.path),
        )
        if errors:
            raise PhaseAuthorizationError(f"authorization profile is invalid: {errors[0].message}")
        if profile.get("status") != "qualified":
            raise PhaseAuthorizationError("authorization profile is not qualified")
        if profile.get("profile_id") != profile_ref.get("id") or profile.get("version") != profile_ref.get("version"):
            raise PhaseAuthorizationError("authorization profile identity does not match its reference")
        return profile

    def resolve_owner_approval(
        self, approval_ref: Mapping[str, Any], *, subject: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Resolve and validate the DPC-owner provenance artifact for v2."""

        if approval_ref.get("semantic_type") != "dpc-owner-approval":
            raise PhaseAuthorizationError("owner approval reference has the wrong semantic type")
        approval = self._resolve_indexed_ref(approval_ref)
        schema = json.loads(
            (self.root / "contracts" / "dpc-owner-approval.v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(approval),
            key=lambda error: list(error.path),
        )
        if errors:
            raise PhaseAuthorizationError(f"owner approval is invalid: {errors[0].message}")
        if approval.get("subject") != dict(subject):
            raise PhaseAuthorizationError("owner approval subject does not match authorization")
        return approval

    def require_phase034_pass(self) -> None:
        index = self._index()
        acceptance_entry = next(
            (
                item
                for item in index["entries"]
                if item["id"] == "phase-034-acceptance-record"
            ),
            None,
        )
        manifest_entry = next(
            (
                item
                for item in index["entries"]
                if item["id"] == "phase-034-source-state-manifest-v1"
            ),
            None,
        )
        if acceptance_entry is None or manifest_entry is None:
            raise PhaseAuthorizationError(
                "Phase 034 prerequisite artifacts are not indexed"
            )
        record = self._resolve_indexed_ref(acceptance_entry)
        schema = json.loads(
            (
                self.root / "contracts" / "phase-034-acceptance-record.v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                record
            ),
            key=lambda error: list(error.path),
        )
        if errors:
            raise PhaseAuthorizationError(
                f"Phase 034 acceptance record is invalid: {errors[0].message}"
            )
        manifest = self._resolve_indexed_ref(manifest_entry)
        if record.get("status") != "PASS":
            raise PhaseAuthorizationError("Phase 034 independent PASS is not retained")
        if (
            record.get("phase_id") != "P034"
            or record.get("specification_hash") != EXPECTED_PHASE034_SPECIFICATION_HASH
        ):
            raise PhaseAuthorizationError(
                "Phase 034 prerequisite does not match the accepted specification"
            )
        review = record.get("independent_review", {})
        required_evidence = {
            "phase-034-scope-boundary-evidence",
            "phase-034-authorization-evidence",
            "phase-034-source-state-manifest",
            "phase-034-focused-test-evidence",
            "phase-034-specification-hash-evidence",
        }
        if (
            review.get("decision") != "PASS"
            or review.get("authority") != "development-platform-core.independent-review"
            or review.get("request_ref") != "phase-034-independent-review-request"
            or not required_evidence.issubset(set(review.get("evidence_refs", [])))
        ):
            raise PhaseAuthorizationError(
                "Phase 034 independent review evidence is incomplete"
            )
        if (
            record.get("source_state_manifest_ref") != manifest_entry["id"]
            or record.get("source_state_manifest_digest") != manifest_entry["digest"]
            or canonical_digest(manifest) != manifest_entry["digest"]
        ):
            raise PhaseAuthorizationError(
                "Phase 034 source-state evidence is incomplete"
            )


def resolve_authorization(
    authorization_ref: str,
    *,
    subject: Mapping[str, Any],
    store: FileAuthorizationStore | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_store = store or FileAuthorizationStore()
    record = resolved_store.resolve(authorization_ref)
    if record["decision"] != "approved":
        raise PhaseAuthorizationError("authorization decision is not approved")
    if record.get("revoked_at") is not None:
        raise PhaseAuthorizationError("authorization is revoked")
    current = now or datetime.now(UTC)
    if (
        record["valid_until"] is not None
        and datetime.fromisoformat(record["valid_until"].replace("Z", "+00:00"))
        <= current
    ):
        raise PhaseAuthorizationError("authorization is expired")
    if record["issuer"] != "development-platform-core.phase-authority":
        raise PhaseAuthorizationError("authorization issuer is not approved")
    if record["subject"] != dict(subject):
        raise PhaseAuthorizationError(
            "authorization subject does not match phase specification"
        )
    if record.get("schema") == V1_AUTHORIZATION_SCHEMA:
        if record["scope"] != {
            "scope_type": "core_qualification_only",
            "scope_id": "P033-core-qualification",
            "excluded_authorities": [
                "global_forge",
                "consumer_workflows",
                "runtime",
                "batch",
                "herdr_transport",
                "orca_transport",
                "opensandbox_target_execution",
                "remediation",
                "deployment",
                "production_authority",
            ],
        }:
            raise PhaseAuthorizationError("authorization scope is outside Core qualification")
        resolved_store.require_phase034_pass()
    elif record.get("schema") == V2_AUTHORIZATION_SCHEMA:
        profile = resolved_store.resolve_profile(record["profile_ref"])
        resolved_store.resolve_owner_approval(
            record["owner_approval_ref"], subject=record["subject"]
        )
        if record["scope"] != profile["scope"]:
            raise PhaseAuthorizationError("authorization scope does not match its profile")
        prerequisites = profile["prerequisites"]
        if prerequisites["phase034_pass_required"]:
            resolved_store.require_phase034_pass()
        refs = [record["authority_binding"], record["owner_approval_ref"], record["review_request_ref"], *record["lineage"]]
        available_types = {ref["semantic_type"] for ref in refs}
        missing = sorted(set(prerequisites["required_lineage_types"]) - available_types)
        if missing:
            raise PhaseAuthorizationError(
                "authorization profile prerequisites are incomplete: " + ", ".join(missing)
            )
    else:
        raise PhaseAuthorizationError("authorization schema version is unsupported")
    return record
