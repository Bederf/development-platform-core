"""Approval-gated project-phase admission through the Core index.

This service closes the admission-to-binding gap without granting execution
authority. It accepts only an attributable, subject-bound binding decision;
it never infers approval from a Product Owner specification record or from a
missing resolver binding.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .gsd_phase_resolver import _resolve_project_phase
from .phase_authorization import FileAuthorizationStore
from .phase_specification import validate_phase_specification


class ProjectPhaseAdmissionError(ValueError):
    """Raised when a project phase cannot be admitted safely."""


def _canonical_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("digest", None)
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _raw_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ProjectPhaseAdmissionError(f"refusing to overwrite existing artifact: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with open(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_index(path: Path) -> dict[str, Any]:
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectPhaseAdmissionError("Core authorization index is unavailable") from exc
    if not isinstance(index, dict) or _canonical_digest(index) != index.get("digest"):
        raise ProjectPhaseAdmissionError("Core authorization index digest is invalid")
    entries = index.get("entries")
    if not isinstance(entries, list):
        raise ProjectPhaseAdmissionError("Core authorization index entries are invalid")
    return index


def _resolve_staged_admission(
    *,
    project_id: str,
    repository_root: str | Path,
    planning_root: str | Path,
    phase_id: str,
    subject: Mapping[str, Any],
    staged_index: Path,
) -> Any:
    """Resolve candidate authority from isolated staged artifacts.

    The public resolver is intentionally backed by the live Core authority
    index. Admission therefore validates the same resolver semantics against a
    test-only authorization store whose index and binding point at staged
    artifacts, before either artifact is published.
    """

    selected = _resolve_project_phase(planning_root, phase_id)
    if selected.specification_hash != subject["specification_hash"]:
        raise ProjectPhaseAdmissionError("staged phase digest does not match the approved subject")
    store = FileAuthorizationStore(
        index_path=staged_index,
        root=Path(__file__).resolve().parents[1],
        test_only=True,
    )
    binding_id = f"project-{project_id}-phase-{phase_id[1:]}-specification-binding"
    try:
        store.resolve_project_phase_specification_binding(binding_id, subject=subject)
    except Exception as exc:  # normalize resolver/store failures at the admission boundary
        raise ProjectPhaseAdmissionError("staged project phase authority is not resolvable") from exc
    return selected


def admit_project_phase(
    *,
    project_id: str,
    repository_root: str | Path,
    planning_root: str | Path,
    specification_path: str | Path,
    approval_record_path: str | Path,
    binding_path: str | Path,
    index_path: str | Path,
    approval: Mapping[str, Any],
    scope_type: str = "project_consumer_phase",
    excluded_authorities: list[str],
    replacement: bool = False,
) -> dict[str, Any]:
    """Issue, index and resolve one explicitly approved project phase.

    ``approval`` is deliberately supplied by the caller and must be bound to
    the exact subject. This function does not create authority or accept a
    Product Owner decision as DPC binding authority by implication.
    """

    if not project_id.strip() or not scope_type.strip() or not excluded_authorities:
        raise ProjectPhaseAdmissionError("project identity, scope and exclusions are required")
    if approval.get("decision") != "approved" or approval.get("binding_issuance_authorized") is not True:
        raise ProjectPhaseAdmissionError("explicit DPC binding-issuance approval is required")
    if replacement and approval.get("replacement_authorized") is not True:
        raise ProjectPhaseAdmissionError("explicit replacement-binding authorization is required")
    if not approval.get("approver") or not approval.get("approver_capacity"):
        raise ProjectPhaseAdmissionError("attributable approver and capacity are required")

    spec_path = Path(specification_path)
    try:
        specification = json.loads(spec_path.read_text(encoding="utf-8"))
        resolution = validate_phase_specification(specification)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProjectPhaseAdmissionError("project phase specification is invalid") from exc

    subject = {
        "project_id": project_id,
        "repository_root": str(Path(repository_root).resolve()),
        "planning_root": str(Path(planning_root).resolve()),
        "phase_id": resolution.phase_id,
        "specification_id": resolution.specification_id,
        "specification_version": resolution.version,
        "specification_hash": resolution.specification_hash,
    }
    expected_subject = approval.get("subject")
    if expected_subject != subject:
        raise ProjectPhaseAdmissionError("approval is not bound to the exact project phase subject")

    record_path = Path(approval_record_path)
    if not record_path.is_file() or record_path.is_symlink():
        raise ProjectPhaseAdmissionError("approval record is unavailable or unsafe")
    binding_id = f"project-{project_id}-phase-{resolution.phase_id[1:]}-specification-binding"
    binding = {
        "schema": "core-project-phase-specification-binding.v1",
        "binding_id": binding_id,
        "version": "1.0.0",
        "decision": "approved",
        "issuer": "development-platform-core.phase-authority",
        "authority_binding": {
            "semantic_type": "authority_binding",
            "id": "core-phase-authority",
            "version": "1.0.0",
            "digest": "sha256:a0f5bf1b3de81f1c4f47385be824841c90a3b08117cf2de8f3152cd1545439ae",
        },
        "scope": {
            "scope_type": scope_type,
            "project_id": project_id,
            "excluded_authorities": list(dict.fromkeys(excluded_authorities)),
        },
        "subject": subject,
        "approval_basis": {
            "record_path": str(record_path),
            "record_sha256": _raw_digest(record_path),
            "approver": approval["approver"],
            "approver_capacity": approval["approver_capacity"],
            "execution_excluded": True,
        },
    }
    if replacement:
        binding["supersedes_binding"] = {
            "binding_id": binding_id,
            "historical": True,
            "replacement_authorized": True,
        }
    binding["digest"] = _canonical_digest(binding)
    index_file = Path(index_path)
    index = _read_index(index_file)
    entries = index["entries"]
    matches = [item for item in entries if isinstance(item, Mapping) and item.get("id") == binding_id]
    if matches and not replacement:
        raise ProjectPhaseAdmissionError("binding identity is already indexed")
    if replacement and len(matches) != 1:
        raise ProjectPhaseAdmissionError("replacement requires exactly one existing indexed binding")
    if replacement:
        old = matches[0]
        if not isinstance(old.get("path"), str) or not isinstance(old.get("digest"), str):
            raise ProjectPhaseAdmissionError("existing binding evidence is malformed")
        old_path = Path(old["path"])
        if not old_path.is_absolute():
            # Core index paths are Core-root-relative (for example
            # ``docs/assurance/...``), not relative to the consumer subject
            # or the directory containing the index.
            index_root = index_file.resolve().parent.parent.parent
            old_path = index_root / old_path
        if not old_path.is_file():
            raise ProjectPhaseAdmissionError("existing binding evidence is unavailable")
        try:
            old_value = json.loads(old_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectPhaseAdmissionError("existing binding evidence is unavailable") from exc
        # Binding entries are content-addressed by their canonical JSON digest;
        # the archive/file serialization is intentionally not the binding identity.
        if not isinstance(old_value, Mapping) or _canonical_digest(old_value) != old["digest"]:
            raise ProjectPhaseAdmissionError("existing indexed binding digest is invalid")
        candidate_entry = {"id": binding_id, "kind": "project_phase_specification_binding", "path": str(binding_path), "digest": binding["digest"]}
        entries[entries.index(old)] = candidate_entry
    else:
        candidate_entry = {"id": binding_id, "kind": "project_phase_specification_binding", "path": str(binding_path), "digest": binding["digest"]}
        entries.append(candidate_entry)
    index["digest"] = _canonical_digest(index)

    binding_file = Path(binding_path)
    if binding_file.exists() and not replacement:
        raise ProjectPhaseAdmissionError(f"refusing to overwrite existing artifact: {binding_file}")
    original_binding = binding_file.read_bytes() if binding_file.exists() else None
    original_index = index_file.read_bytes()

    with tempfile.TemporaryDirectory(prefix=".phase-admission-", dir=index_file.parent) as staging:
        staging_root = Path(staging)
        staged_binding = staging_root / binding_file.name
        staged_index = staging_root / index_file.name
        _write_json(staged_binding, binding)
        staged_entry = dict(candidate_entry)
        staged_entry["path"] = str(staged_binding)
        staged_index_value = dict(index)
        staged_entries = list(index["entries"])
        staged_entries[staged_entries.index(candidate_entry)] = staged_entry
        staged_index_value["entries"] = staged_entries
        staged_index_value["digest"] = _canonical_digest(staged_index_value)
        _write_json(staged_index, staged_index_value)

        # Resolver/store validation happens entirely against the staged pair.
        resolved = _resolve_staged_admission(
            project_id=project_id,
            repository_root=repository_root,
            planning_root=planning_root,
            phase_id=resolution.phase_id,
            subject=subject,
            staged_index=staged_index,
        )

        index_tmp = index_file.with_name(index_file.name + ".next")
        try:
            _write_json(index_tmp, index)
            os.replace(staged_binding, binding_file)
            os.replace(index_tmp, index_file)
        except Exception as exc:
            # Restore every touched artifact, including a replacement target.
            try:
                if original_binding is None:
                    binding_file.unlink(missing_ok=True)
                else:
                    binding_file.write_bytes(original_binding)
                index_file.write_bytes(original_index)
            finally:
                index_tmp.unlink(missing_ok=True)
            raise ProjectPhaseAdmissionError("admission publication failed and was rolled back") from exc

    # Keep the final result bound to the published path and digest.
    index = _read_index(index_file)
    return {"binding": binding, "index": index, "resolution": resolved}
