"""Resolve project-selected Development Platform capabilities."""

from __future__ import annotations

import json
import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
import yaml


class CapabilitySelectionError(ValueError):
    """Raised when a project capability manifest is unsafe or unsupported."""


def _lexical_absolute(path: Path) -> Path:
    """Normalize dot segments without resolving symlinks."""
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _validate_bundle_filesystem(source_root: Path) -> Path:
    """Require an exact-tree root with regular, singly-linked files only."""
    root = _lexical_absolute(source_root)
    try:
        root_stat = root.stat(follow_symlinks=False)
    except OSError as exc:
        raise CapabilitySelectionError(f"cannot inspect GSD release root: {root}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise CapabilitySelectionError(f"GSD release root must be a real directory: {root}")
    try:
        paths = sorted(root.rglob("*"))
    except OSError as exc:
        raise CapabilitySelectionError(f"cannot enumerate GSD release root: {root}") from exc
    for path in paths:
        try:
            item_stat = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise CapabilitySelectionError(f"cannot inspect GSD release path: {path}") from exc
        mode = item_stat.st_mode
        if stat.S_ISLNK(mode):
            raise CapabilitySelectionError(f"GSD release tree contains a symlink: {path}")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise CapabilitySelectionError(f"GSD release tree contains a special file: {path}")
        if item_stat.st_nlink != 1:
            raise CapabilitySelectionError(f"GSD release tree contains a hard-linked file: {path}")
    return root


def verify_gsd_release_bundle(
    source_root: Path,
    *,
    manifest_path: Path | None = None,
    expected_version: str = "3.3.4",
) -> dict[str, Any]:
    """Verify a promoted GSD bundle against its Core release manifest.

    The check is intentionally fail-closed: missing manifests, missing or
    extra files, byte/size mismatches, and aggregate digest mismatches all
    raise ``CapabilitySelectionError``.
    """

    root = _validate_bundle_filesystem(source_root)
    manifest = (manifest_path or Path(__file__).resolve().parents[2] / "capabilities" / f"gsd-master.v{expected_version}.manifest.json").resolve()
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilitySelectionError(f"cannot read GSD release manifest: {manifest}") from exc
    if payload.get("schema") != "gsd-master-release-manifest.v1":
        raise CapabilitySelectionError("unsupported GSD release manifest schema")
    if payload.get("capability_id") != "gsd.master" or payload.get("version") != expected_version:
        raise CapabilitySelectionError("GSD release manifest identity does not match the requested version")

    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise CapabilitySelectionError("GSD release manifest has no file entries")
    expected: dict[str, dict[str, Any]] = {}
    for entry in entries:
        relative = entry.get("path") if isinstance(entry, dict) else None
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        size = entry.get("bytes") if isinstance(entry, dict) else None
        if not isinstance(relative, str) or not isinstance(digest, str) or not isinstance(size, int):
            raise CapabilitySelectionError("GSD release manifest contains an invalid file entry")
        if Path(relative).is_absolute() or ".." in Path(relative).parts or relative in expected:
            raise CapabilitySelectionError(f"unsafe or duplicate GSD release path: {relative}")
        expected[relative] = {"sha256": digest, "bytes": size}

    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts and ".serena" not in path.relative_to(root).parts
    }
    if actual_files != set(expected):
        missing = sorted(set(expected) - actual_files)
        extra = sorted(actual_files - set(expected))
        raise CapabilitySelectionError(f"GSD release file set mismatch: missing={missing!r}, extra={extra!r}")

    canonical_lines: list[bytes] = []
    for relative in sorted(expected):
        path = root / relative
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        expected_entry = expected[relative]
        if len(content) != expected_entry["bytes"] or digest != expected_entry["sha256"]:
            raise CapabilitySelectionError(f"GSD release file digest/size mismatch: {relative}")
        canonical_lines.append(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
    aggregate = "sha256:" + hashlib.sha256(b"".join(canonical_lines)).hexdigest()
    if aggregate != payload.get("bundle_digest"):
        raise CapabilitySelectionError(
            f"GSD release bundle digest mismatch: expected {payload.get('bundle_digest')}, observed {aggregate}"
        )
    return {
        "capability_id": "gsd.master",
        "version": expected_version,
        "source_root": str(root),
        "manifest": str(manifest),
        "bundle_digest": aggregate,
        "files": len(expected),
        "status": "verified",
    }


def default_gsd_source_root(version: str) -> Path | None:
    """Derive the installed GSD bundle root from the capability definition.

    The capability definition declares ``informative.metadata.implementation_reference``
    as ``external:<path-to-SKILL.md>``. That file's parent directory is the bundle
    root, so verification can run against the actual installed implementation
    without the caller having to supply a path.

    Returns ``None`` when the definition is missing, unreadable, or carries no
    usable external reference — in which case the caller must fail closed rather
    than verify nothing.
    """

    definition = Path(__file__).resolve().parents[2] / "capabilities" / f"gsd-master.v{version}.json"
    try:
        payload = json.loads(definition.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    metadata = payload.get("informative", {})
    if not isinstance(metadata, dict):
        return None
    metadata = metadata.get("metadata", {})
    if not isinstance(metadata, dict):
        return None
    reference = metadata.get("implementation_reference")
    if not isinstance(reference, str) or not reference.startswith("external:"):
        return None
    target = Path(reference[len("external:") :]).expanduser()
    return target.parent if target.name else target


CAPABILITY_REGISTRY: dict[str, dict[str, str]] = {
    "ocr": {"implementation": "core.ocr-gate", "version": "1.0.0", "readiness": "ready", "adapter": "core-hook-wrapper"},
    "backpass": {"implementation": "core.backpass", "version": "1.0.0", "readiness": "requires-central-ingestion", "adapter": "project-session-capture"},
    "property-testing": {"implementation": "project-defined", "version": "1.0.0", "readiness": "project-adapter-required", "adapter": "project-test-runner"},
    "gsd": {"implementation": "gsd.master", "version": "3.3.4", "readiness": "ready", "adapter": "external-skill"},
    "governed-engineering-loop": {"implementation": "core.governed-engineering-loop", "version": "1.0.0", "readiness": "ready", "adapter": "core-skill-projection"},
    "security-audit": {"implementation": "core.security-audit-build", "version": "1.0.2", "readiness": "ready", "adapter": "explicit-build-release-command"},
}

WORKFLOW_PROVIDER_REGISTRY: dict[str, dict[str, str]] = {
    "native-gsd": {"version": "3.3.4", "readiness": "ready"},
    "spec-kit": {"version": "1.0.4", "readiness": "ready"},
}
WORKFLOW_STAGES = {"SPECIFICATION", "ASSESSMENT", "PLAN", "TASKS", "IMPLEMENTATION", "CONVERGENCE"}

# Declared compatibility window for promoted versions.
#
# The registry `version` above is the *current promoted* version. Entries here list
# the additional versions that remain selectable during a transition, so promoting a
# version does not simultaneously reject every existing consumer declaration.
#
# Exact match against the registry version remains the default: a capability or
# provider absent from these maps accepts only its registered version. Remove an
# entry once no consumer declares it.
CAPABILITY_COMPATIBILITY_WINDOW: dict[str, tuple[str, ...]] = {
    # gsd.master 3.3.4 promoted 2026-10-12; 3.3.0 remains a qualified predecessor.
    # 3.4.0-preview.1 is an explicitly selected developer-preview candidate;
    # it is not the promoted default and must provide its own source_root and
    # release_manifest until separately promoted.
    "gsd": ("3.4.0-preview.1", "3.3.0"),
}
WORKFLOW_PROVIDER_COMPATIBILITY_WINDOW: dict[str, tuple[str, ...]] = {
    "native-gsd": ("3.3.0",),
}


def accepted_capability_versions(capability_id: str) -> tuple[str, ...]:
    """Return every version selectable for a capability: promoted first, then window."""
    registered = CAPABILITY_REGISTRY[capability_id]["version"]
    return (registered, *CAPABILITY_COMPATIBILITY_WINDOW.get(capability_id, ()))


def accepted_provider_versions(provider: str) -> tuple[str, ...]:
    """Return every version selectable for a workflow provider."""
    registered = WORKFLOW_PROVIDER_REGISTRY[provider]["version"]
    return (registered, *WORKFLOW_PROVIDER_COMPATIBILITY_WINDOW.get(provider, ()))


def normalize_workflow_providers(configuration: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Normalize explicit GSD workflow-provider choices without activating them."""

    raw = configuration.get("workflow_providers", {})
    if not isinstance(raw, dict):
        raise CapabilitySelectionError("gsd workflow_providers must be an object")
    normalized: dict[str, dict[str, str]] = {}
    for stage, selection in sorted(raw.items()):
        if stage not in WORKFLOW_STAGES:
            raise CapabilitySelectionError(f"unsupported GSD workflow stage: {stage}")
        if not isinstance(selection, dict):
            raise CapabilitySelectionError(f"GSD workflow provider selection must be an object: {stage}")
        provider = selection.get("provider")
        version = selection.get("version")
        registered = WORKFLOW_PROVIDER_REGISTRY.get(provider)
        if registered is None:
            raise CapabilitySelectionError(f"unsupported GSD workflow provider: {provider}")
        if version not in accepted_provider_versions(provider):
            raise CapabilitySelectionError(
                f"GSD workflow provider version does not match Core registry: {provider} "
                f"(expected {' or '.join(accepted_provider_versions(provider))})"
            )
        normalized[stage] = {
            "provider": provider,
            "version": version,
            "readiness": registered["readiness"],
        }
    return normalized


def _load_profile_registry() -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    profile_dir = Path(__file__).resolve().parents[2] / "capabilities" / "profiles"
    for profile_path in sorted(profile_dir.glob("*.json")):
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilitySelectionError(f"cannot read capability profile: {profile_path}") from exc
        if profile.get("entity_type") != "capability_profile":
            raise CapabilitySelectionError(f"invalid capability profile entity: {profile_path}")
        profile_id = profile.get("profile_id")
        version = profile.get("version")
        base = profile.get("base_capability", {})
        if not isinstance(profile_id, str) or not isinstance(version, str) or not isinstance(base, dict):
            raise CapabilitySelectionError(f"invalid capability profile catalog entry: {profile_path}")
        base_id = base.get("id")
        if not isinstance(base_id, str):
            raise CapabilitySelectionError(f"capability profile base is missing: {profile_path}")
        if profile_id in catalog:
            raise CapabilitySelectionError(f"duplicate capability profile: {profile_id}")
        catalog[profile_id] = {"version": version, "base_capability": base_id}
    return catalog


PROFILE_REGISTRY = _load_profile_registry()


def resolve_capabilities(
    repository_root: Path,
    project_id: str,
    manifest_name: str = ".development-platform/capabilities.yaml",
) -> dict[str, Any]:
    """Return normalized selections without activating capabilities."""

    manifest = (repository_root / manifest_name).resolve()
    try:
        manifest.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise CapabilitySelectionError("capability manifest must be inside the project repository") from exc
    if not manifest.is_file():
        return {
            "schema": "development-capability-selection.v1",
            "status": "unavailable",
            "manifest_path": str(manifest),
            "reason": "capability selection manifest is absent",
            "selections": {},
        }

    try:
        payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CapabilitySelectionError(f"cannot read capability manifest: {exc}") from exc
    schema_path = Path(__file__).resolve().parents[2] / "contracts" / "capability-selection.v1.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilitySelectionError(f"cannot read capability selection schema: {exc}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "document"
        raise CapabilitySelectionError(f"invalid capability manifest at {location}: {errors[0].message}")
    if payload.get("project_id") != project_id:
        raise CapabilitySelectionError("capability manifest project_id does not match declaration")
    selections = payload.get("capabilities")
    if not isinstance(selections, dict):
        raise CapabilitySelectionError("capabilities must be a YAML object")

    normalized: dict[str, dict[str, Any]] = {}
    for capability_id, selection in sorted(selections.items()):
        if capability_id not in CAPABILITY_REGISTRY:
            raise CapabilitySelectionError(f"unsupported capability: {capability_id}")
        if not isinstance(selection, dict):
            raise CapabilitySelectionError(f"capability selection must be an object: {capability_id}")
        if not isinstance(selection.get("enabled"), bool):
            raise CapabilitySelectionError(f"capability enabled must be boolean: {capability_id}")
        implementation = selection.get("implementation")
        version = selection.get("version")
        if not isinstance(implementation, str) or not implementation.strip():
            raise CapabilitySelectionError(f"capability implementation is required: {capability_id}")
        if not isinstance(version, str) or not version.strip():
            raise CapabilitySelectionError(f"capability version is required: {capability_id}")
        registry = CAPABILITY_REGISTRY[capability_id]
        expected_implementation = registry["implementation"]
        selectable_versions = accepted_capability_versions(capability_id)
        if selection["enabled"] and (implementation != expected_implementation or version not in selectable_versions):
            raise CapabilitySelectionError(
                f"enabled capability does not match Core registry: {capability_id} "
                f"(expected {expected_implementation}@{' or '.join(selectable_versions)})"
            )
        configuration = selection.get("configuration", {})
        if not isinstance(configuration, dict):
            raise CapabilitySelectionError(f"capability configuration must be an object: {capability_id}")
        normalized_configuration = dict(configuration)
        if capability_id == "gsd":
            normalized_configuration["workflow_providers"] = normalize_workflow_providers(configuration)
            if selection["enabled"] and version in accepted_capability_versions("gsd"):
                source_root = configuration.get("source_root")
                if not isinstance(source_root, str) or not source_root.strip():
                    # Fall back to the installed implementation declared by the
                    # capability definition, so the standard flow verifies the real
                    # bundle instead of requiring every caller to supply a path.
                    default_root = default_gsd_source_root(version)
                    if default_root is None:
                        raise CapabilitySelectionError(
                            f"enabled gsd.master {version} selection requires source_root, and no "
                            "usable implementation_reference was found in the capability definition"
                        )
                    source_root = str(default_root)
                manifest_reference = configuration.get("release_manifest")
                if manifest_reference is not None and not isinstance(manifest_reference, str):
                    raise CapabilitySelectionError("gsd release_manifest must be a path string when provided")
                normalized_configuration["release_verification"] = verify_gsd_release_bundle(
                    Path(source_root),
                    manifest_path=Path(manifest_reference) if manifest_reference else None,
                    expected_version=version,
                )
        profiles = selection.get("profiles", [])
        if not isinstance(profiles, list):
            raise CapabilitySelectionError(f"capability profiles must be a list: {capability_id}")
        normalized_profiles: list[dict[str, str]] = []
        for profile in profiles:
            if not isinstance(profile, dict):
                raise CapabilitySelectionError(f"capability profile must be an object: {capability_id}")
            profile_id = profile.get("id")
            profile_version = profile.get("version")
            if not isinstance(profile_id, str) or not isinstance(profile_version, str):
                raise CapabilitySelectionError(f"capability profile requires id and version: {capability_id}")
            registered = PROFILE_REGISTRY.get(profile_id)
            if registered is None:
                raise CapabilitySelectionError(f"unsupported capability profile: {profile_id}")
            if registered["base_capability"] != capability_id:
                raise CapabilitySelectionError(
                    f"capability profile base does not match selection: {profile_id}"
                )
            if profile_version != registered["version"]:
                raise CapabilitySelectionError(
                    f"capability profile version does not match Core registry: {profile_id} "
                    f"(expected {registered['version']})"
                )
            if not selection["enabled"]:
                raise CapabilitySelectionError(
                    f"profiles cannot be selected for a disabled capability: {capability_id}"
                )
            normalized_profiles.append({"id": profile_id, "version": profile_version})
        normalized[capability_id] = {
            "enabled": selection["enabled"],
            "implementation": implementation,
            "version": version,
            "readiness": registry["readiness"],
            "adapter": registry["adapter"],
            "profiles": normalized_profiles,
            "configuration": normalized_configuration,
        }

    return {
        "schema": "development-capability-selection.v1",
        "status": "resolved",
        "manifest_path": str(manifest),
        "reason": None,
        "selections": normalized,
    }
