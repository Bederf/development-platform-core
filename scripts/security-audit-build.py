#!/usr/bin/env python3
"""Validate a pinned, source-only Cloudflare security-audit package.

This is an explicit build/release assurance boundary. It is intentionally not
called by the pre-commit gate and never executes target code, provider code,
network operations, credentials, or shared services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/assurance/CLOUDFLARE-SECURITY-AUDIT-SOURCE-MANIFEST-v1.json"
RUN_SCHEMA = ROOT / "contracts/security-audit-build-run.v1.schema.json"
COMMIT = "c1c8a8c1471069fb0e188eeaff69b8e8db6564a8"
EXPECTED = (
    "run-metadata.json",
    "architecture.md",
    "coverage-ledger.json",
    "findings.json",
    "REPORT.md",
    "FINDINGS-DETAIL.md",
    "NEEDS-VALIDATION.md",
)
VALIDATORS = {
    "coverage": (
        "skills/security-audit/validate-coverage-ledger.cjs",
        "2eb280bd2e33c002916f86db9b29f9edfedb6454e5db973c766290465b868ac8",
    ),
    "findings": (
        "skills/security-audit/validate-findings.cjs",
        "e85f232e36bfac0f866f244da50376692d6b45c690beadcb00608b0e6c8b5283",
    ),
}


class AuditPackageError(ValueError):
    """Raised when a build-time audit package cannot be trusted."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditPackageError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditPackageError(f"JSON root must be an object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source(source: Path) -> dict[str, str]:
    manifest = load_json(MANIFEST)
    if (
        manifest.get("commit") != COMMIT
        or manifest.get("repository")
        != "https://github.com/cloudflare/security-audit-skill"
    ):
        raise AuditPackageError(
            "Cloudflare source manifest is not the pinned Phase 032 manifest"
        )
    try:
        observed = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AuditPackageError(
            f"source checkout is not a readable Git checkout: {source}"
        ) from exc
    if observed != COMMIT:
        raise AuditPackageError(f"Cloudflare checkout commit mismatch: {observed!r}")
    entries = {entry["path"]: entry["sha256"] for entry in manifest.get("files", [])}
    for name, (relative, expected) in VALIDATORS.items():
        declared = entries.get(relative)
        if declared != expected:
            raise AuditPackageError(
                f"validator hash declaration mismatch for {name}: "
                f"expected {expected}, manifest has {declared!r}"
            )
    for relative, expected in entries.items():
        path = source / relative
        if not path.is_file() or sha256(path) != expected:
            raise AuditPackageError(f"Cloudflare source hash mismatch: {relative}")
    return {
        name: str(source / relative) for name, (relative, _digest) in VALIDATORS.items()
    }


def validate_metadata(package: Path) -> dict[str, Any]:
    metadata = load_json(package / "run-metadata.json")
    schema = load_json(RUN_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(metadata),
        key=lambda error: list(error.path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "root"
        raise AuditPackageError(
            f"invalid run metadata at {location}: {errors[0].message}"
        )
    if metadata["incomplete_reason"] is None and metadata["run_status"] != "complete":
        raise AuditPackageError("incomplete or blocked runs require incomplete_reason")
    if (
        metadata["run_status"] == "complete"
        and metadata["incomplete_reason"] is not None
    ):
        raise AuditPackageError("complete runs must have incomplete_reason=null")
    return metadata


def validate_artifacts(package: Path, metadata: dict[str, Any]) -> None:
    actual = {path.name for path in package.iterdir() if path.is_file()}
    expected = set(EXPECTED)
    if actual != expected:
        raise AuditPackageError(
            f"root artifact set mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    if metadata["run_status"] != "complete":
        return
    for name in EXPECTED:
        if not (package / name).is_file():
            raise AuditPackageError(f"required artifact missing: {name}")


def validate_global_boundary() -> None:
    try:
        configuration = yaml.safe_load(
            (ROOT / "development-platform.yaml").read_text(encoding="utf-8")
        )
        actual = {
            "forge": configuration["forge"],
            "runtime": configuration["runtime"],
            "batch": configuration["batch"],
            "herdr": configuration["herdr"],
        }
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise AuditPackageError(
            "development-platform.yaml cannot be parsed for boundary validation"
        ) from exc
    expected = {
        "forge": {"enabled": False},
        "runtime": {"enabled": False},
        "batch": {"enabled": False},
        "herdr": {"enabled": False, "lifecycle_transport": False},
    }
    if actual != expected:
        raise AuditPackageError(f"global execution boundary is not disabled: {actual}")


def run_validator(executable: Path, artifact: Path) -> None:
    try:
        result = subprocess.run(
            ["node", str(executable), str(artifact)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditPackageError(
            f"validator could not complete: {executable.name}"
        ) from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise AuditPackageError(
            f"{executable.name} rejected {artifact.name}: {detail[-1] if detail else 'unknown error'}"
        )


def validate_package(package: Path, source: Path) -> dict[str, Any]:
    if not package.is_dir():
        raise AuditPackageError(f"audit package is not a directory: {package}")
    validator_paths = validate_source(source)
    validate_global_boundary()
    metadata = validate_metadata(package)
    validate_artifacts(package, metadata)
    if metadata["run_status"] == "complete":
        run_validator(
            Path(validator_paths["coverage"]), package / "coverage-ledger.json"
        )
        run_validator(Path(validator_paths["findings"]), package / "findings.json")
    return {
        "status": "validated"
        if metadata["run_status"] == "complete"
        else metadata["run_status"],
        "run_id": metadata["run_id"],
        "package": str(package),
        "source_commit": COMMIT,
        "artifacts": list(EXPECTED),
        "validators": {name: str(path) for name, path in validator_paths.items()},
        "target_execution": metadata["target_execution"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        type=Path,
        required=True,
        help="retained seven-artifact audit package",
    )
    parser.add_argument(
        "--cloudflare-source",
        type=Path,
        required=True,
        help="local read-only checkout at the pinned commit",
    )
    args = parser.parse_args(argv)
    try:
        print(
            json.dumps(
                validate_package(
                    args.package.resolve(), args.cloudflare_source.resolve()
                ),
                sort_keys=True,
            )
        )
        return 0
    except (AuditPackageError, OSError, TypeError, ValueError) as exc:
        print(f"security audit build gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
