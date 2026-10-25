"""Core validation and inheritance checks for project-definition.v1.

This module is deliberately provider-neutral and non-mutating. It validates a
canonical project definition, resolves its governance reference, verifies
content digests, and projects immutable project constraints into a phase input.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
PROJECT_SCHEMA_PATH = ROOT / "contracts" / "project-definition.v1.schema.json"
GOVERNANCE_SCHEMA_PATH = ROOT / "contracts" / "project-governance.v1.schema.json"


class ProjectDefinitionError(ValueError):
    """Raised when a project definition or inherited phase is untrusted."""


@dataclass(frozen=True)
class ProjectDefinitionResolution:
    definition_id: str
    project_id: str
    version: str
    digest: str
    governance_path: Path


@dataclass(frozen=True)
class PhaseInheritance:
    project_id: str
    definition_id: str
    definition_digest: str
    in_scope: tuple[str, ...]
    non_goals: tuple[str, ...]
    architecture_constraints: tuple[str, ...]
    security_constraints: tuple[str, ...]
    authority_restrictions: tuple[str, ...]


def _jcs_number(value: int | float) -> str:
    """Serialize the JSON number subset used by Core's canonical records.

    Python integers are already valid shortest JSON integers. For finite
    floating-point values, ``repr`` supplies the shortest round-trippable
    representation; the normalization below applies ECMAScript/JCS exponent
    thresholds and spelling rules.
    """

    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ProjectDefinitionError("RFC 8785 does not permit non-finite numbers")
    if value == 0:
        return "0"
    raw = repr(value).lower()
    if "e" not in raw:
        if raw.endswith(".0"):
            return raw[:-2]
        return raw
    mantissa, exponent_text = raw.split("e", 1)
    exponent = int(exponent_text)
    sign = ""
    if mantissa.startswith("-"):
        sign, mantissa = "-", mantissa[1:]
    digits = mantissa.replace(".", "")
    decimal_position = (mantissa.find(".") if "." in mantissa else len(mantissa)) + exponent
    magnitude = abs(value)
    if 1e-6 <= magnitude < 1e21:
        if decimal_position <= 0:
            return sign + "0." + ("0" * -decimal_position) + digits
        if decimal_position >= len(digits):
            return sign + digits + ("0" * (decimal_position - len(digits)))
        return sign + digits[:decimal_position] + "." + digits[decimal_position:]
    normalized_exponent = f"{exponent:+d}"
    significant = digits[0]
    remainder = digits[1:].rstrip("0")
    if remainder:
        significant += "." + remainder
    return f"{sign}{significant}e{normalized_exponent}"


def canonicalize_jcs(value: Any) -> bytes:
    """Return RFC 8785/JCS-style UTF-8 canonical JSON bytes.

    Object keys are sorted by UTF-16 code units as required by JCS. Strings
    are emitted without ASCII expansion, and non-finite numbers are rejected.
    Core project-definition records contain no binary values or custom types.
    """

    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _jcs_number(value).encode("ascii")
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ProjectDefinitionError("RFC 8785 rejects lone UTF-16 surrogates")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(canonicalize_jcs(item) for item in value) + b"]"
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ProjectDefinitionError("canonical JSON object keys must be strings")
        items = sorted(value.items(), key=lambda item: item[0].encode("utf-16-be"))
        return b"{" + b",".join(
            canonicalize_jcs(key) + b":" + canonicalize_jcs(item) for key, item in items
        ) + b"}"
    raise ProjectDefinitionError(f"unsupported canonical JSON value: {type(value).__name__}")


def project_definition_digest(document: Mapping[str, Any]) -> str:
    """Calculate the project-definition digest excluding its self-digest."""

    payload = json.loads(json.dumps(document))
    payload.pop("digest", None)
    return "sha256:" + hashlib.sha256(canonicalize_jcs(payload)).hexdigest()


def _validate_schema(document: Mapping[str, Any], path: Path, label: str) -> None:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectDefinitionError(f"{label} schema is unavailable") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "root"
        raise ProjectDefinitionError(f"invalid {label} at {location}: {errors[0].message}")


def _resolve_locator(locator: str, governance_root: Path | None) -> Path:
    parsed = urlparse(locator)
    if parsed.scheme and parsed.scheme != "file":
        raise ProjectDefinitionError(f"unsupported governance locator scheme: {parsed.scheme}")
    if parsed.scheme == "file":
        if parsed.netloc not in {"", "localhost"}:
            raise ProjectDefinitionError("remote file governance locators are not permitted")
        path = Path(unquote(parsed.path))
    else:
        relative = Path(locator)
        if not relative.is_absolute():
            if governance_root is None:
                raise ProjectDefinitionError("relative governance locator requires governance_root")
            if ".." in relative.parts:
                raise ProjectDefinitionError("governance locator escapes governance_root")
            path = governance_root / relative
        else:
            path = relative
    if path.is_symlink():
        raise ProjectDefinitionError("governance locator may not be a symlink")
    root = governance_root.resolve() if governance_root is not None else None
    path = path.resolve()
    if root is not None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ProjectDefinitionError("governance locator escapes governance_root") from exc
    if not path.is_file():
        raise ProjectDefinitionError("governance locator is unavailable or unsafe")
    return path


def validate_project_definition(
    document: Mapping[str, Any],
    *,
    governance_root: str | Path | None = None,
    verify_digest: bool = True,
) -> ProjectDefinitionResolution:
    """Validate a definition and its exact governance reference without writes."""

    if not isinstance(document, Mapping):
        raise ProjectDefinitionError("project definition must be an object")
    _validate_schema(document, PROJECT_SCHEMA_PATH, "project-definition.v1")
    if verify_digest and document["digest"] != project_definition_digest(document):
        raise ProjectDefinitionError("project-definition digest does not match canonical RFC 8785 content")

    reference = document["governance_ref"]
    root = Path(governance_root).resolve() if governance_root is not None else None
    governance_path = _resolve_locator(reference["locator"], root)
    try:
        governance = json.loads(governance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectDefinitionError("governance record is unavailable or invalid JSON") from exc
    if not isinstance(governance, Mapping):
        raise ProjectDefinitionError("governance record must be an object")
    _validate_schema(governance, GOVERNANCE_SCHEMA_PATH, "project-governance.v1")
    if governance["context_id"] != reference["context_id"]:
        raise ProjectDefinitionError("governance context_id does not match governance_ref")
    if governance["project_id"] != document["project"]["project_id"]:
        raise ProjectDefinitionError("governance project_id does not match project definition")
    if governance["status"] not in {"confirmed", "reconciled"}:
        raise ProjectDefinitionError("governance record is not in an approved lifecycle state")
    if project_definition_digest(governance) != reference["digest"]:
        raise ProjectDefinitionError("governance digest does not match governance_ref")
    return ProjectDefinitionResolution(
        document["definition_id"],
        document["project"]["project_id"],
        document["version"],
        document["digest"],
        governance_path,
    )


def inherit_project_constraints(
    document: Mapping[str, Any],
    phase: Mapping[str, Any],
    *,
    governance: Mapping[str, Any],
) -> PhaseInheritance:
    """Check that a phase narrows, rather than weakens, project authority."""

    if not isinstance(governance, Mapping):
        raise ProjectDefinitionError("governance record is required for authority inheritance")
    if document.get("status") != "approved":
        raise ProjectDefinitionError("phase inheritance requires an approved project definition")
    if not isinstance(phase, Mapping):
        raise ProjectDefinitionError("phase inheritance input must be an object")
    project = document["project"]
    reference = phase.get("project_ref")
    if not isinstance(reference, Mapping):
        raise ProjectDefinitionError("phase project_ref is required")
    expected = {
        "project_id": project["project_id"],
        "definition_id": document["definition_id"],
        "definition_version": document["version"],
        "definition_digest": document["digest"],
    }
    if dict(reference) != expected:
        raise ProjectDefinitionError("phase is not bound to the exact project definition")
    scope = phase.get("scope")
    if not isinstance(scope, Mapping):
        raise ProjectDefinitionError("phase scope is required")
    project_in = set(document["boundaries"]["in_scope"])
    project_out = set(document["boundaries"]["out_of_scope"])
    phase_in = tuple(scope.get("in_scope", []))
    phase_non_goals = tuple(scope.get("non_goals", []))
    if not set(phase_in).issubset(project_in):
        raise ProjectDefinitionError("phase widens project in-scope boundary")
    if not project_out.issubset(set(phase_non_goals)):
        raise ProjectDefinitionError("phase does not inherit project exclusions")
    if set(phase_in) & project_out:
        raise ProjectDefinitionError("phase includes a project out-of-scope item")

    architecture = tuple(phase.get("architecture_constraints", []))
    security = tuple(phase.get("security_constraints", []))
    if not set(document["architecture"]["constraints"]).issubset(set(architecture)):
        raise ProjectDefinitionError("phase weakens inherited architecture constraints")
    if not set(document["security"]["constraints"]).issubset(set(security)):
        raise ProjectDefinitionError("phase weakens inherited security constraints")

    authority_restrictions: set[str] = set()
    for authority in governance.get("authority", {}).values():
        authority_restrictions.update(authority.get("prohibited", []))
    phase_authority = set(phase.get("authority_restrictions", []))
    if not authority_restrictions.issubset(phase_authority):
        raise ProjectDefinitionError("phase weakens inherited authority restrictions")
    return PhaseInheritance(
        project["project_id"],
        document["definition_id"],
        document["digest"],
        phase_in,
        phase_non_goals,
        architecture,
        security,
        tuple(sorted(phase_authority)),
    )
