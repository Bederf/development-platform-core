"""Codex-specific verification of the selected GSD projection.

This module verifies the bytes Radix is about to expose to Codex. It does not
claim that Codex subsequently parsed or used those bytes.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .capabilities import CapabilitySelectionError, verify_gsd_release_bundle


class GsdProjectionError(ValueError):
    """Raised when a Codex GSD projection cannot be established safely."""


DISCOVERY_AFFECTING_FLAGS = frozenset(
    {"--add-dir", "--plugin-dir", "--config", "--settings", "--bare"}
)
EXPECTED_SKILL_NAMES = frozenset({"gsd-master"})
EXPECTED_SKILL_ALIASES = frozenset({"gsd:master"})


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise GsdProjectionError(f"cannot read GSD skill metadata: {path}") from exc
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _candidate_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if not root.is_dir():
        raise GsdProjectionError(f"Codex skill discovery root is not a directory: {root}")
    candidates: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        metadata_path = child / "SKILL.md"
        if not metadata_path.is_file():
            continue
        metadata = _frontmatter(metadata_path)
        if metadata.get("name") in EXPECTED_SKILL_NAMES or metadata.get("alias") in EXPECTED_SKILL_ALIASES:
            candidates.append(Path(os.path.abspath(os.fspath(child))))
    return candidates


def _discovery_roots(project_root: Path, environ: Mapping[str, str]) -> tuple[Path, ...]:
    roots: list[Path] = []
    codex_home = environ.get("CODEX_HOME")
    if codex_home:
        configured = Path(codex_home).expanduser()
        if not configured.is_absolute():
            raise GsdProjectionError("CODEX_HOME must be an absolute path")
        roots.append(Path(os.path.abspath(os.fspath(configured / "skills"))))
    else:
        roots.append(Path(os.path.abspath(os.fspath(Path.home() / ".codex" / "skills"))))
    roots.append(Path(os.path.abspath(os.fspath(project_root / ".codex" / "skills"))))
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return tuple(unique)


def _validate_projection_root(path: Path) -> Path:
    """Reject links and special files before canonicalizing a projection."""
    lexical = Path(os.path.abspath(os.fspath(path.expanduser())))
    try:
        root_stat = lexical.stat(follow_symlinks=False)
    except OSError as exc:
        raise GsdProjectionError(f"cannot inspect Codex GSD projection: {lexical}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise GsdProjectionError(f"Codex GSD projection must be a real directory: {lexical}")
    for child in sorted(lexical.rglob("*")):
        try:
            child_stat = child.stat(follow_symlinks=False)
        except OSError as exc:
            raise GsdProjectionError(f"cannot inspect Codex GSD projection path: {child}") from exc
        mode = child_stat.st_mode
        if stat.S_ISLNK(mode):
            raise GsdProjectionError(f"Codex GSD projection contains a symlink: {child}")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise GsdProjectionError(f"Codex GSD projection contains a special file: {child}")
        if child_stat.st_nlink != 1:
            raise GsdProjectionError(f"Codex GSD projection contains a hard-linked file: {child}")
    return lexical


def reject_discovery_overrides(args: list[str]) -> None:
    """Reject arguments whose discovery behavior Radix cannot observe safely."""
    for index, argument in enumerate(args):
        option = argument.split("=", 1)[0]
        if option in DISCOVERY_AFFECTING_FLAGS:
            raise GsdProjectionError(
                f"Codex discovery-affecting argument is outside the controlled Radix profile: {argument}"
            )
        if option in {"-c", "--config"} and index + 1 < len(args):
            raise GsdProjectionError("Codex configuration override is outside the controlled Radix profile")


def verify_codex_projection(
    *,
    project_root: Path,
    capability: Mapping[str, Any],
    agent_args: list[str],
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Verify the one Codex GSD projection selected for a Radix launch."""
    if capability.get("enabled") is not True or capability.get("implementation") != "gsd.master":
        raise GsdProjectionError("enabled gsd.master capability is required for Codex projection verification")
    version = capability.get("version")
    if not isinstance(version, str) or not version:
        raise GsdProjectionError("GSD capability version is missing")
    configuration = capability.get("configuration", {})
    if not isinstance(configuration, dict):
        raise GsdProjectionError("GSD capability configuration is invalid")
    reject_discovery_overrides(agent_args)

    release_configuration = configuration.get("release_verification", {})
    if not isinstance(release_configuration, dict):
        raise GsdProjectionError("GSD release_verification configuration is invalid")
    source_root_value = configuration.get("source_root") or release_configuration.get("source_root")
    if not isinstance(source_root_value, str) or not source_root_value.strip():
        raise GsdProjectionError("GSD source_root is required for projection verification")
    source_root = Path(source_root_value).expanduser().resolve()
    manifest_value = configuration.get("release_manifest") or release_configuration.get("manifest")
    manifest_path = Path(manifest_value).expanduser().resolve() if isinstance(manifest_value, str) else None
    try:
        release = verify_gsd_release_bundle(
            source_root,
            manifest_path=manifest_path,
            expected_version=version,
        )
    except CapabilitySelectionError as exc:
        raise GsdProjectionError(str(exc)) from exc

    roots = _discovery_roots(project_root, environ)
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(_candidate_dirs(root))
    candidates = sorted(set(Path(os.path.abspath(os.fspath(candidate))) for candidate in candidates))

    if len(candidates) > 1:
        configured_projection = configuration.get("projection_path")
        if not isinstance(configured_projection, str) or not configured_projection.strip():
            raise GsdProjectionError(f"ambiguous Codex GSD projections: {[str(path) for path in candidates]}")
    else:
        configured_projection = configuration.get("projection_path")
    selected: Path | None = None
    if configured_projection is not None:
        if not isinstance(configured_projection, str) or not configured_projection.strip():
            raise GsdProjectionError("projection_path must be a non-empty path")
        selected = Path(os.path.abspath(os.fspath(Path(configured_projection).expanduser())))
        if selected not in candidates:
            raise GsdProjectionError(f"configured GSD projection was not discovered: {selected}")
    elif len(candidates) == 1:
        selected = candidates[0]
    elif not candidates:
        raise GsdProjectionError("no Codex GSD projection was discovered")
    else:
        raise GsdProjectionError(f"ambiguous Codex GSD projections: {[str(path) for path in candidates]}")

    selected = _validate_projection_root(selected)
    try:
        projection = verify_gsd_release_bundle(
            selected,
            manifest_path=manifest_path,
            expected_version=version,
        )
    except CapabilitySelectionError as exc:
        raise GsdProjectionError(f"Codex GSD projection failed release verification: {exc}") from exc
    return {
        "capability_id": "gsd.master",
        "version": version,
        "release_bundle_digest": release["bundle_digest"],
        "projection_path": str(selected),
        "projection_bundle_digest": projection["bundle_digest"],
        "projection_file_count": projection["files"],
        "discovery_roots": [str(root) for root in roots],
        "discovered_candidates": [str(path) for path in candidates],
        "harness": "codex",
        "activation": "radix-launch",
        "actual_consumption": "UNVERIFIED",
        "result": "verified",
    }


def write_launch_attestation(
    *,
    project_root: Path,
    session_id: str,
    project_id: str,
    projection: Mapping[str, Any],
) -> Path:
    """Atomically persist non-authoritative launch-time projection evidence."""
    directory = project_root / ".development-platform" / "attestations"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"radix-gsd-codex-{session_id}.json"
    payload = {
        "schema": "radix-gsd-launch-attestation.v1",
        "layer": "harness_projection",
        "project_id": project_id,
        "session_id": session_id,
        "projection": dict(projection),
        "authoritative": False,
        "actual_consumption": "UNVERIFIED",
    }
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(directory), text=True)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path
