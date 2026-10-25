import json
import hashlib
from pathlib import Path

import pytest

from adapters.phase_authorization import FileAuthorizationStore
from adapters.gsd_phase_resolver import (
    GsdPhaseResolutionError,
    _resolve_authoritative_dpc_phase,
    _resolve_authoritative_project_phase,
    _resolve_dpc_phase,
)
from adapters.phase_specification import calculate_specification_hash


def _spec(phase_id: str = "P040") -> dict:
    value = {
        "schema": "phase-specification.v1",
        "phase": {
            "specification_id": "radix-codex-gsd-projection-verification",
            "phase_id": phase_id,
            "title": "Radix Codex GSD Projection Verification",
            "version": "1.0.0",
            "specification_hash": "",
            "created_at": "2026-10-15T00:00:00Z",
            "updated_at": "2026-10-15T00:00:00Z",
            "created_by": "core-owner",
            "provenance": {"source_refs": ["ADR-024"], "supersedes_ref": None},
            "workflow": {"schema": "development-workflow.v1", "workflow_id": None},
        },
        "intent": {"objective": "test", "desired_outcome": "test", "business_context": "test"},
        "scope": {"in_scope": ["test"], "non_goals": ["test"], "constraints": ["test"]},
        "requirements": [
            {
                "requirement_id": "P040-R001",
                "statement": "test",
                "mandatory": True,
                "acceptance_criteria": [{"criterion_id": "P040-C001", "statement": "test"}],
                "evidence_contract": [{"evidence_type": "test", "required": True, "producer": "test", "verification_method": "test"}],
                "verification_method": "test",
                "dependencies": [],
            }
        ],
        "implementation": {"tasks": [{"task_id": "P040-T001", "statement": "test", "depends_on": [], "requirement_refs": ["P040-R001"], "expected_artifacts": ["test"]}], "execution_strategy": "test"},
        "verification": {"required_checks": ["test"], "required_evidence": ["test"], "forge_required": False, "live_verification_required": False},
        "independent_review": {"required": True, "authority": "development-platform-core.independent-review", "required_context": ["test"], "required_evidence": ["test"], "remediation_on_findings": "test"},
        "convergence": {"required": True, "required_conditions": ["test"], "failure_states": ["BLOCKED"]},
        "remediation": {"retry_policy": "test", "rework_policy": "test", "escalation_policy": "test"},
        "acceptance": {"authority": "development-platform-core.acceptance-authority", "workflow_schema": "development-workflow.v1", "required_conditions": ["test"]},
    }
    value["phase"]["specification_hash"] = calculate_specification_hash(value)
    return value


def _write(root: Path, name: str = "Phase-040-Radix-Codex.md", phase_id: str = "P040") -> None:
    (root / name).write_text(f"---\nphase_id: {phase_id}\n---\n", encoding="utf-8")
    spec = _spec(phase_id)
    (root / (name.removesuffix(".md") + ".specification.json")).write_text(json.dumps(spec), encoding="utf-8")


def _write_authority(repository: Path, specification_hash: str, phase_id: str = "P040") -> None:
    assurance = repository / "docs" / "assurance"
    assurance.mkdir(parents=True, exist_ok=True)
    authority = {
        "schema": "core-phase-authority-binding.v1",
        "binding_id": "core-phase-authority",
        "version": "1.0.0",
        "issuer": "development-platform-core.phase-authority",
    }
    authority["digest"] = "sha256:" + hashlib.sha256(json.dumps(authority, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (assurance / "CORE-PHASE-AUTHORITY-BINDING-v1.json").write_text(json.dumps(authority), encoding="utf-8")
    record = {
        "schema": "core-phase-specification-binding.v1",
        "binding_id": f"phase-{phase_id[1:]}-specification-binding",
        "version": "1.0.0",
        "decision": "approved",
        "issuer": "development-platform-core.phase-authority",
        "authority_binding": {"semantic_type": "authority_binding", "id": "core-phase-authority", "version": "1.0.0", "digest": authority["digest"]},
        "scope": {"scope_type": "core_qualification_only", "scope_id": f"{phase_id}-resolver-compatibility"},
        "subject": {"phase_id": phase_id, "specification_id": "radix-codex-gsd-projection-verification", "specification_version": "1.0.0", "specification_hash": specification_hash},
    }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    record["digest"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    binding_path = assurance / f"PHASE-{phase_id[1:]}-SPECIFICATION-BINDING-v1.json"
    binding_path.write_text(json.dumps(record), encoding="utf-8")
    index = {"schema": "core-authorization-index.v1", "index_id": "core-authorization-index", "entries": [
        {"id": "core-phase-authority", "kind": "authority_binding", "path": "docs/assurance/CORE-PHASE-AUTHORITY-BINDING-v1.json", "digest": authority["digest"]},
        {"id": f"phase-{phase_id[1:]}-specification-binding", "kind": "phase_specification_binding", "path": f"docs/assurance/PHASE-{phase_id[1:]}-SPECIFICATION-BINDING-v1.json", "digest": record["digest"]},
    ]}
    index["digest"] = "sha256:" + hashlib.sha256(json.dumps(index, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (assurance / "CORE-AUTHORIZATION-INDEX-v1.json").write_text(json.dumps(index), encoding="utf-8")


def test_resolves_unique_descriptive_dpc_phase_and_preserves_identity(tmp_path):
    _write(tmp_path)
    result = _resolve_dpc_phase(tmp_path, "040")
    assert result.phase_id == "P040"
    assert result.specification_id == "radix-codex-gsd-projection-verification"
    assert result.specification_hash == _spec()["phase"]["specification_hash"]
    assert result.markdown_path.name == "Phase-040-Radix-Codex.md"


@pytest.mark.parametrize("case", ["missing", "duplicate", "missing_sidecar", "bad_hash", "wrong_identity", "symlink"])
def test_resolution_fails_closed_for_invalid_authority_inputs(tmp_path, case):
    _write(tmp_path)
    markdown = next(tmp_path.glob("Phase-040-*.md"))
    if case == "missing":
        markdown.unlink()
        markdown.with_name(markdown.name.removesuffix(".md") + ".specification.json").unlink()
    elif case == "duplicate":
        _write(tmp_path, "Phase-040-Other.md")
    elif case == "missing_sidecar":
        markdown.with_name(markdown.name.removesuffix(".md") + ".specification.json").unlink()
    elif case == "bad_hash":
        spec_path = markdown.with_name(markdown.name.removesuffix(".md") + ".specification.json")
        spec = json.loads(spec_path.read_text())
        spec["phase"]["specification_hash"] = "sha256:" + "0" * 64
        spec_path.write_text(json.dumps(spec))
    elif case == "wrong_identity":
        spec_path = markdown.with_name(markdown.name.removesuffix(".md") + ".specification.json")
        spec = _spec("P041")
        spec_path.write_text(json.dumps(spec))
    else:
        replacement = tmp_path / "Phase-040-Symlink.md"
        replacement.symlink_to(markdown)
        markdown.unlink()
        markdown = replacement
    with pytest.raises(GsdPhaseResolutionError):
        _resolve_dpc_phase(tmp_path, "040")


def test_exact_and_descriptive_phase_candidates_are_ambiguous(tmp_path):
    _write(tmp_path)
    _write(tmp_path, "Phase-040.md")
    with pytest.raises(GsdPhaseResolutionError, match="ambiguous"):
        _resolve_dpc_phase(tmp_path, "040")


def test_authoritative_resolution_rejects_recomputed_hash_tampering(tmp_path):
    (tmp_path / "00-GSD-Phases").mkdir()
    root = tmp_path / "00-GSD-Phases"
    _write(root)
    approved_hash = _spec()["phase"]["specification_hash"]
    _write_authority(tmp_path, approved_hash)
    path = next(root.glob("*.specification.json"))
    spec = json.loads(path.read_text())
    spec["phase"]["title"] = "tampered"
    spec["phase"]["specification_hash"] = calculate_specification_hash(spec)
    path.write_text(json.dumps(spec))
    with pytest.raises(GsdPhaseResolutionError, match="does not match the subject"):
        _resolve_authoritative_dpc_phase("development-platform-core", tmp_path, root, "040", core_root=tmp_path, authority_store=FileAuthorizationStore(root=tmp_path, test_only=True))


def test_authoritative_resolution_rejects_duplicate_identity_with_different_digest(tmp_path):
    (tmp_path / "00-GSD-Phases").mkdir()
    root = tmp_path / "00-GSD-Phases"
    _write(root)
    _write_authority(tmp_path, _spec()["phase"]["specification_hash"])
    duplicate = _spec()
    duplicate["phase"]["title"] = "different"
    duplicate["phase"]["specification_hash"] = calculate_specification_hash(duplicate)
    (root / "Phase-040-Other.specification.json").write_text(json.dumps(duplicate))
    with pytest.raises(GsdPhaseResolutionError, match="not uniquely bound"):
        _resolve_authoritative_dpc_phase("development-platform-core", tmp_path, root, "040", core_root=tmp_path, authority_store=FileAuthorizationStore(root=tmp_path, test_only=True))


def test_authoritative_resolution_rejects_alternative_root(tmp_path):
    (tmp_path / "00-GSD-Phases").mkdir()
    _write(tmp_path / "00-GSD-Phases")
    _write_authority(tmp_path, _spec()["phase"]["specification_hash"])
    alternative = tmp_path.parent / (tmp_path.name + "-alternative")
    alternative.mkdir()
    _write(alternative)
    with pytest.raises(GsdPhaseResolutionError, match="not the canonical DPC root"):
        _resolve_authoritative_dpc_phase("development-platform-core", tmp_path, alternative, "040", core_root=tmp_path, authority_store=FileAuthorizationStore(root=tmp_path, test_only=True))


def test_authoritative_resolution_uses_subject_bound_p041_binding(tmp_path):
    (tmp_path / "00-GSD-Phases").mkdir()
    root = tmp_path / "00-GSD-Phases"
    _write(root, "Phase-041-Future.md", phase_id="P041")
    _write_authority(tmp_path, _spec("P041")["phase"]["specification_hash"], phase_id="P041")
    result = _resolve_authoritative_dpc_phase(
        "development-platform-core", tmp_path, root, "041",
        core_root=tmp_path,
        authority_store=FileAuthorizationStore(root=tmp_path, test_only=True),
    )
    assert result.phase_id == "P041"


def test_authoritative_resolution_reports_missing_p041_binding(tmp_path):
    (tmp_path / "00-GSD-Phases").mkdir()
    root = tmp_path / "00-GSD-Phases"
    _write(root, "Phase-041-Future.md", phase_id="P041")
    _write_authority(tmp_path, _spec("P040")["phase"]["specification_hash"], phase_id="P040")
    with pytest.raises(GsdPhaseResolutionError, match="missing or ambiguous"):
        _resolve_authoritative_dpc_phase(
            "development-platform-core", tmp_path, root, "041",
            core_root=tmp_path,
            authority_store=FileAuthorizationStore(root=tmp_path, test_only=True),
        )


def test_authoritative_resolution_rejects_stale_indexed_binding_digest(tmp_path):
    (tmp_path / "00-GSD-Phases").mkdir()
    root = tmp_path / "00-GSD-Phases"
    _write(root, "Phase-041-Future.md", phase_id="P041")
    _write_authority(tmp_path, _spec("P041")["phase"]["specification_hash"], phase_id="P041")
    binding = tmp_path / "docs" / "assurance" / "PHASE-041-SPECIFICATION-BINDING-v1.json"
    record = json.loads(binding.read_text())
    record["scope"]["scope_id"] = "stale-binding"
    binding.write_text(json.dumps(record))
    with pytest.raises(GsdPhaseResolutionError, match="artifact digest is invalid"):
        _resolve_authoritative_dpc_phase(
            "development-platform-core", tmp_path, root, "041",
            core_root=tmp_path,
            authority_store=FileAuthorizationStore(root=tmp_path, test_only=True),
        )


def test_authoritative_resolution_rejects_p041_binding_with_wrong_subject(tmp_path):
    (tmp_path / "00-GSD-Phases").mkdir()
    root = tmp_path / "00-GSD-Phases"
    _write(root, "Phase-041-Future.md", phase_id="P041")
    _write_authority(tmp_path, _spec("P040")["phase"]["specification_hash"], phase_id="P041")
    with pytest.raises(GsdPhaseResolutionError, match="invalid or does not match the subject"):
        _resolve_authoritative_dpc_phase(
            "development-platform-core", tmp_path, root, "041",
            core_root=tmp_path,
            authority_store=FileAuthorizationStore(root=tmp_path, test_only=True),
        )


def _write_project_authority(core_root: Path, project_root: Path, project_id: str, spec):
    assurance = core_root / "docs" / "assurance"
    assurance.mkdir(parents=True, exist_ok=True)
    authority = {
        "schema": "core-phase-authority-binding.v1",
        "binding_id": "core-phase-authority",
        "version": "1.0.0",
        "issuer": "development-platform-core.phase-authority",
        "scope": "core-qualification-only",
    }
    authority["digest"] = "sha256:" + hashlib.sha256(
        json.dumps(authority, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (assurance / "CORE-PHASE-AUTHORITY-BINDING-v1.json").write_text(
        json.dumps(authority), encoding="utf-8"
    )
    subject = {
        "project_id": project_id,
        "repository_root": str(project_root.resolve()),
        "planning_root": str((project_root / ".development-platform" / "gsd-phases").resolve()),
        "phase_id": "P040",
        "specification_id": spec["phase"]["specification_id"],
        "specification_version": spec["phase"]["version"],
        "specification_hash": spec["phase"]["specification_hash"],
    }
    binding = {
        "schema": "core-project-phase-specification-binding.v1",
        "binding_id": f"project-{project_id}-phase-040-specification-binding",
        "version": "1.0.0",
        "decision": "approved",
        "issuer": "development-platform-core.phase-authority",
        "authority_binding": {
            "semantic_type": "authority_binding",
            "id": "core-phase-authority",
            "version": "1.0.0",
            "digest": authority["digest"],
        },
        "scope": {
            "scope_type": "project_consumer_phase",
            "project_id": project_id,
            "excluded_authorities": [
                "implementation", "consumer_activation", "deployment",
                "production_authority", "physical_control",
            ],
        },
        "subject": subject,
    }
    binding["digest"] = "sha256:" + hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    binding_path = assurance / "PROJECT-ALPHA-PHASE-040-BINDING.json"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    index = {
        "schema": "core-authorization-index.v1",
        "index_id": "core-authorization-index",
        "entries": [
            {
                "id": "core-phase-authority",
                "kind": "authority_binding",
                "path": "docs/assurance/CORE-PHASE-AUTHORITY-BINDING-v1.json",
                "digest": authority["digest"],
            },
            {
                "id": binding["binding_id"],
                "kind": "project_phase_specification_binding",
                "path": str(binding_path.relative_to(core_root)),
                "digest": binding["digest"],
            },
        ],
    }
    index["digest"] = "sha256:" + hashlib.sha256(
        json.dumps(index, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (assurance / "CORE-AUTHORIZATION-INDEX-v1.json").write_text(
        json.dumps(index), encoding="utf-8"
    )


def test_project_phase_resolves_from_project_root_through_core_binding(tmp_path):
    core = tmp_path / "core"
    project = tmp_path / "project-alpha"
    planning = project / ".development-platform" / "gsd-phases"
    core.mkdir()
    planning.mkdir(parents=True)
    _write(planning, phase_id="P040")
    spec = json.loads(next(planning.glob("*.specification.json")).read_text())
    _write_project_authority(core, project, "project-alpha", spec)
    result = _resolve_authoritative_project_phase(
        "project-alpha", project, planning, "040",
        core_root=core,
        authority_store=FileAuthorizationStore(root=core, test_only=True),
    )
    assert result.specification_path.parent == planning


def test_project_phase_binding_namespaces_projects_and_rejects_root_mismatch(tmp_path):
    core = tmp_path / "core"
    project = tmp_path / "project-alpha"
    other = tmp_path / "project-beta"
    planning = project / ".development-platform" / "gsd-phases"
    core.mkdir()
    planning.mkdir(parents=True)
    _write(planning, phase_id="P040")
    spec = json.loads(next(planning.glob("*.specification.json")).read_text())
    _write_project_authority(core, project, "project-alpha", spec)
    with pytest.raises(GsdPhaseResolutionError, match="missing or ambiguous"):
        _resolve_authoritative_project_phase(
            "project-beta", project, planning, "040",
            core_root=core,
            authority_store=FileAuthorizationStore(root=core, test_only=True),
        )
    other.mkdir()
    with pytest.raises(GsdPhaseResolutionError, match="project planning root"):
        _resolve_authoritative_project_phase(
            "project-alpha", other, planning, "040",
            core_root=core,
            authority_store=FileAuthorizationStore(root=core, test_only=True),
        )


def test_multiple_projects_can_bind_same_phase_number_without_collision(tmp_path):
    core = tmp_path / "core"
    alpha = tmp_path / "project-alpha"
    beta = tmp_path / "project-beta"
    core.mkdir()
    for project, project_id in ((alpha, "project-alpha"), (beta, "project-beta")):
        planning = project / ".development-platform" / "gsd-phases"
        planning.mkdir(parents=True)
        _write(planning, phase_id="P040")
        spec = json.loads(next(planning.glob("*.specification.json")).read_text())
        if project_id == "project-alpha":
            _write_project_authority(core, project, project_id, spec)
        else:
            assurance = core / "docs" / "assurance"
            binding = {
                "schema": "core-project-phase-specification-binding.v1",
                "binding_id": "project-project-beta-phase-040-specification-binding",
                "version": "1.0.0",
                "decision": "approved",
                "issuer": "development-platform-core.phase-authority",
                "authority_binding": {
                    "semantic_type": "authority_binding",
                    "id": "core-phase-authority",
                    "version": "1.0.0",
                    "digest": json.loads(
                        (assurance / "CORE-PHASE-AUTHORITY-BINDING-v1.json").read_text()
                    )["digest"],
                },
                "scope": {
                    "scope_type": "project_consumer_phase",
                    "project_id": project_id,
                    "excluded_authorities": [
                        "implementation", "consumer_activation", "deployment",
                        "production_authority", "physical_control",
                    ],
                },
                "subject": {
                    "project_id": project_id,
                    "repository_root": str(project.resolve()),
                    "planning_root": str(planning.resolve()),
                    "phase_id": "P040",
                    "specification_id": spec["phase"]["specification_id"],
                    "specification_version": spec["phase"]["version"],
                    "specification_hash": spec["phase"]["specification_hash"],
                },
            }
            binding["digest"] = "sha256:" + hashlib.sha256(
                json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            path = assurance / "PROJECT-BETA-PHASE-040-BINDING.json"
            path.write_text(json.dumps(binding), encoding="utf-8")
            index_path = assurance / "CORE-AUTHORIZATION-INDEX-v1.json"
            index = json.loads(index_path.read_text())
            index["entries"].append({
                "id": binding["binding_id"],
                "kind": "project_phase_specification_binding",
                "path": str(path.relative_to(core)),
                "digest": binding["digest"],
            })
            index.pop("digest", None)
            index["digest"] = "sha256:" + hashlib.sha256(
                json.dumps(index, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            index_path.write_text(json.dumps(index), encoding="utf-8")
    store = FileAuthorizationStore(root=core, test_only=True)
    alpha_result = _resolve_authoritative_project_phase(
        "project-alpha", alpha, alpha / ".development-platform" / "gsd-phases", "040",
        core_root=core, authority_store=store,
    )
    beta_result = _resolve_authoritative_project_phase(
        "project-beta", beta, beta / ".development-platform" / "gsd-phases", "040",
        core_root=core, authority_store=store,
    )
    assert alpha_result.specification_path.parent != beta_result.specification_path.parent


def test_core_phase_resolution_remains_separate_from_project_resolution(tmp_path):
    core = tmp_path / "core"
    root = core / "00-GSD-Phases"
    root.mkdir(parents=True)
    _write(root, phase_id="P040")
    _write_authority(core, _spec()["phase"]["specification_hash"])
    result = _resolve_authoritative_dpc_phase(
        "development-platform-core", core, root, "040",
        core_root=core,
        authority_store=FileAuthorizationStore(root=core, test_only=True),
    )
    assert result.phase_id == "P040"
    with pytest.raises(GsdPhaseResolutionError, match="DPC Core phases"):
        _resolve_authoritative_project_phase(
            "development-platform-core", core, root, "040",
            core_root=core,
            authority_store=FileAuthorizationStore(root=core, test_only=True),
        )
