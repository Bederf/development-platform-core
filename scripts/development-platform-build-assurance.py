#!/usr/bin/env python3
"""Run explicitly requested Core build assurance for a project."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class BuildAssuranceError(ValueError):
    """Raised when a project is not eligible for build assurance."""


def _project_id(project: Path, supplied: str | None) -> str:
    if supplied:
        return supplied
    manifest = project / ".development-platform/capabilities.yaml"
    try:
        payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BuildAssuranceError(
            "cannot determine project id; provide --project-id or a valid capability manifest"
        ) from exc
    project_id = payload.get("project_id") if isinstance(payload, dict) else None
    if not isinstance(project_id, str) or not project_id:
        raise BuildAssuranceError("capability manifest does not contain a project_id")
    return project_id


def _resolve_security_audit(project: Path, project_id: str) -> dict[str, Any]:
    from adapters.radix.capabilities import CapabilitySelectionError, resolve_capabilities

    try:
        resolution = resolve_capabilities(project, project_id)
    except CapabilitySelectionError as exc:
        raise BuildAssuranceError(f"capability resolution failed: {exc}") from exc
    if resolution.get("status") != "resolved":
        raise BuildAssuranceError(
            "security-audit baseline is unavailable; run approved Radix project initialization first"
        )
    selection = resolution.get("selections", {}).get("security-audit")
    if not isinstance(selection, dict) or not selection.get("enabled"):
        raise BuildAssuranceError("security-audit baseline is not enabled for this project")
    configuration = selection.get("configuration", {})
    if not isinstance(configuration, dict):
        raise BuildAssuranceError("security-audit configuration is invalid")
    if configuration.get("execution") != "explicit-build-release":
        raise BuildAssuranceError("security-audit is not configured for explicit build/release execution")
    if configuration.get("pre_commit") != "disabled" or configuration.get("production") != "disabled":
        raise BuildAssuranceError("security-audit execution boundary is not disabled for pre-commit and production")
    return resolution


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project repository root (default: current directory)")
    parser.add_argument("--project-id", help="project id; otherwise read it from the capability manifest")
    parser.add_argument("--audit-package", type=Path, required=True, help="retained seven-artifact audit package")
    parser.add_argument("--cloudflare-source", type=Path, required=True, help="pinned read-only Cloudflare source checkout")
    args = parser.parse_args(argv)
    try:
        project = args.project.expanduser().resolve()
        if not project.is_dir():
            raise BuildAssuranceError(f"project directory does not exist: {project}")
        project_id = _project_id(project, args.project_id)
        _resolve_security_audit(project, project_id)
        command = [
            str(ROOT / "bin/security-audit-build"),
            "--package",
            str(args.audit_package.expanduser().resolve()),
            "--cloudflare-source",
            str(args.cloudflare_source.expanduser().resolve()),
        ]
        completed = subprocess.run(command, cwd=project, check=False)
        return completed.returncode
    except (BuildAssuranceError, OSError, TypeError, ValueError) as exc:
        print(f"development-platform build assurance failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
