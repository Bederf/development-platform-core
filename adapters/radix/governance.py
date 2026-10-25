"""Validation and binding of the project governance context used by Radix."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


class GovernanceContextError(ValueError):
    """Raised when a project governance context is absent or invalid."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    payload = deepcopy(dict(value))
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        provenance.pop("record_digest", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def governance_digest(record: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(record)).hexdigest()


def validate_governance_record(
    record: Mapping[str, Any],
    *,
    project_id: str,
    repository_root: Path,
    require_established: bool = True,
) -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[2] / "contracts" / "project-governance.v1.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceContextError("project governance schema is unavailable") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record),
        key=lambda error: list(error.path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "document"
        raise GovernanceContextError(f"invalid governance context at {location}: {errors[0].message}")
    if record["project_id"] != project_id:
        raise GovernanceContextError("governance project_id does not match declaration")
    if Path(record["repository_root"]).expanduser().resolve() != repository_root.resolve():
        raise GovernanceContextError("governance repository_root does not match declaration")
    expected = governance_digest(record)
    if record["provenance"]["record_digest"] != expected:
        raise GovernanceContextError("governance record_digest does not match record contents")
    if require_established and record["status"] not in {"confirmed", "reconciled"}:
        raise GovernanceContextError("governance context is not confirmed or reconciled")
    return deepcopy(dict(record))


def load_governance_record(
    path: Path,
    *,
    project_id: str,
    repository_root: Path,
    require_established: bool = True,
) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceContextError(f"cannot read governance context: {path}") from exc
    if not isinstance(record, Mapping):
        raise GovernanceContextError("governance context must be a JSON object")
    return validate_governance_record(
        record,
        project_id=project_id,
        repository_root=repository_root,
        require_established=require_established,
    )
