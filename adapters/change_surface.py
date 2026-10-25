"""Provider-neutral, non-authoritative Forge change-surface verification."""

from __future__ import annotations

import json
import hashlib
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "contracts" / "change-surface-verification.v1.schema.json"
EXPECTED_SCHEMA_PATH = ROOT / "contracts" / "change-surface-expected.v1.schema.json"
ACTUAL_SCHEMA_PATH = ROOT / "contracts" / "change-surface-actual.v1.schema.json"
SIGNALS = frozenset({"PASS", "REVIEW_REQUIRED", "INCOMPLETE"})
RISK_LEVELS = {"low": 0, "medium": 1, "high": 2}
CANONICALIZATION = "json-sort-keys-separators-v1"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ChangeSurfaceVerificationError(ValueError):
    """Raised when a change-surface observation cannot be evaluated safely."""


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ChangeSurfaceVerificationError(f"{name} must be a non-empty string")
    return value


def _validate_path(value: Any, name: str) -> str:
    path = _required_text(value, name)
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ChangeSurfaceVerificationError(f"{name} must be repository-relative: {path!r}")
    return path


def _validate_paths(values: Any, name: str) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ChangeSurfaceVerificationError(f"{name} must be an array of paths")
    return [_validate_path(item, name) for item in values]


def _validate_identity(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ChangeSurfaceVerificationError(f"{name} must be an object")
    fields = ("project_id", "phase_id", "work_id", "request_id", "attempt_id", "repository", "baseline")
    return {field: _required_text(value.get(field), f"{name}.{field}") for field in fields}


def _validate_risk(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ChangeSurfaceVerificationError(f"{name} must be an object")
    fields = ("risk", "blast_radius")
    result = {field: _required_text(value.get(field), f"{name}.{field}") for field in fields}
    if any(item not in RISK_LEVELS for item in result.values()):
        raise ChangeSurfaceVerificationError(f"{name} risk values must be low, medium, or high")
    return result


def canonical_digest(value: Mapping[str, Any]) -> str:
    """Digest a contract after removing its self-referential digest field."""
    payload = deepcopy(dict(value))
    payload.pop("evidence_digest", None)
    payload.pop("observation_digest", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_bound_contract(value: Any, schema_path: Path, digest_field: str, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ChangeSurfaceVerificationError(f"{name} must be an object")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(item) for item in errors[0].path) or name
        raise ChangeSurfaceVerificationError(f"invalid {name} at {location}: {errors[0].message}")
    if value.get("canonicalization") != CANONICALIZATION:
        raise ChangeSurfaceVerificationError(f"unsupported {name} canonicalization")
    supplied = value.get(digest_field)
    if not isinstance(supplied, str) or not DIGEST_PATTERN.fullmatch(supplied):
        raise ChangeSurfaceVerificationError(f"{name} digest must use sha256:<64 lowercase hex>")
    try:
        calculated = canonical_digest(value)
    except (TypeError, ValueError) as exc:
        raise ChangeSurfaceVerificationError(f"{name} canonical representation is not deterministic") from exc
    if supplied != calculated:
        raise ChangeSurfaceVerificationError(f"{name} digest does not bind the supplied canonical evidence")
    return dict(value)


def _validate_expected(value: Mapping[str, Any]) -> tuple[dict[str, str], list[str], list[str], dict[str, Any]]:
    value = _validate_bound_contract(value, EXPECTED_SCHEMA_PATH, "evidence_digest", "expected change-surface contract")
    identity = _validate_identity(value.get("identity"), "expected.identity")
    digest = value["evidence_digest"]
    authority = _required_text(value.get("authority_ref"), "expected.authority_ref")
    paths = _validate_paths(value.get("expected_paths", []), "expected.expected_paths")
    prefixes = value.get("expected_path_prefixes", [])
    if not isinstance(prefixes, list) or any(not isinstance(item, str) or not item.strip() for item in prefixes):
        raise ChangeSurfaceVerificationError("expected.expected_path_prefixes must be an array of strings")
    expansions = _validate_paths(value.get("authorized_expansions", []), "expected.authorized_expansions")
    risk = _validate_risk(value.get("risk_context"), "expected.risk_context")
    components = value.get("expected_components", [])
    sensitive = value.get("expected_sensitive_dimensions", [])
    for field, items in (("expected_components", components), ("expected_sensitive_dimensions", sensitive)):
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
            raise ChangeSurfaceVerificationError(f"expected.{field} must be an array of strings")
    if not paths and not prefixes and not components:
        raise ChangeSurfaceVerificationError("expected scope must declare paths, prefixes, or components")
    policies = value.get("policies", {})
    if not isinstance(policies, Mapping):
        raise ChangeSurfaceVerificationError("expected.policies must be an object")
    return identity, paths, expansions, {
        "digest": digest,
        "authority": authority,
        "prefixes": prefixes,
        "risk": risk,
        "components": set(components),
        "sensitive": set(sensitive),
        "policies": dict(policies),
    }


def _validate_actual(value: Mapping[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any]]:
    value = _validate_bound_contract(value, ACTUAL_SCHEMA_PATH, "observation_digest", "actual change-surface contract")
    identity = _validate_identity(value.get("identity"), "actual.identity")
    digest = value["observation_digest"]
    revision = _required_text(value.get("revision"), "actual.revision")
    changed = value.get("changed_paths")
    if not isinstance(changed, list):
        raise ChangeSurfaceVerificationError("actual.changed_paths must be an array")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(changed):
        if not isinstance(item, Mapping):
            raise ChangeSurfaceVerificationError(f"actual.changed_paths[{index}] must be an object")
        path = _validate_path(item.get("path"), f"actual.changed_paths[{index}].path")
        status = _required_text(item.get("status"), f"actual.changed_paths[{index}].status")
        if status not in {"added", "modified", "deleted", "renamed"}:
            raise ChangeSurfaceVerificationError(f"unsupported path status: {status!r}")
        category = item.get("category", "source")
        if not isinstance(category, str) or not category.strip():
            raise ChangeSurfaceVerificationError(f"actual.changed_paths[{index}].category must be a string")
        normalized.append({"path": path, "status": status, "category": category, "component": item.get("component")})
    components = value.get("affected_components", [])
    sensitive = value.get("sensitive_dimensions", [])
    unknown = value.get("unknown_dimensions", [])
    for field, items in (("affected_components", components), ("sensitive_dimensions", sensitive), ("unknown_dimensions", unknown)):
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
            raise ChangeSurfaceVerificationError(f"actual.{field} must be an array of strings")
    actual_risk = value.get("risk_context")
    if actual_risk is not None:
        actual_risk = _validate_risk(actual_risk, "actual.risk_context")
    complete = value.get("complete", True)
    if not isinstance(complete, bool):
        raise ChangeSurfaceVerificationError("actual.complete must be boolean")
    return identity, normalized, {
        "digest": digest,
        "revision": revision,
        "components": set(components),
        "sensitive": set(sensitive),
        "unknown": set(unknown),
        "risk": actual_risk,
        "complete": complete,
    }


def _path_allowed(path: str, expected_paths: set[str], prefixes: list[str], expansions: set[str]) -> bool:
    return path in expected_paths or path in expansions or any(path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def evaluate_change_surface(*, expected: Mapping[str, Any], actual: Mapping[str, Any]) -> dict[str, Any]:
    """Compare authorized expected and observed actual surfaces.

    The returned observation is deliberately non-authoritative. Invalid input
    is represented as ``INCOMPLETE`` where possible; malformed input raises so
    callers cannot mistake an invalid request for a valid observation.
    """
    try:
        expected_identity, expected_paths, expansions, expected_meta = _validate_expected(expected)
        actual_identity, changed_paths, actual_meta = _validate_actual(actual)
    except ChangeSurfaceVerificationError as exc:
        identity = expected.get("identity") if isinstance(expected, Mapping) else None
        if not isinstance(identity, Mapping):
            raise
        safe_identity = _validate_identity(identity, "expected.identity")
        result = _result(safe_identity, "INCOMPLETE", [f"invalid evidence: {exc}"])
        return result

    if expected_identity != actual_identity:
        return _result(expected_identity, "INCOMPLETE", ["expected and actual identity do not match"])
    if not actual_meta["complete"] or actual_meta["unknown"]:
        return _result(expected_identity, "INCOMPLETE", ["actual change-surface evidence is incomplete or contains unknown dimensions"], expected_meta["digest"], actual_meta["digest"])

    reasons: list[str] = []
    unexpected_paths = [item["path"] for item in changed_paths if not _path_allowed(item["path"], set(expected_paths), expected_meta["prefixes"], set(expansions))]
    unexpected_components = sorted(actual_meta["components"] - expected_meta["components"]) if expected_meta["components"] else []
    unexpected_sensitive = sorted(actual_meta["sensitive"] - expected_meta["sensitive"])
    actual_risk = actual_meta["risk"]
    risk_escalated = bool(actual_risk and RISK_LEVELS[actual_risk["risk"]] > RISK_LEVELS[expected_meta["risk"]["risk"]])
    blast_escalated = bool(actual_risk and RISK_LEVELS[actual_risk["blast_radius"]] > RISK_LEVELS[expected_meta["risk"]["blast_radius"]])

    raw_allowed_categories = expected_meta["policies"].get("allowed_categories", [])
    if not isinstance(raw_allowed_categories, list) or any(not isinstance(item, str) for item in raw_allowed_categories):
        return _result(expected_identity, "INCOMPLETE", ["expected allowed_categories policy is malformed"], expected_meta["digest"], actual_meta["digest"])
    allowed_categories = set(raw_allowed_categories)
    unexpected_paths = [item["path"] for item in changed_paths if item["path"] in unexpected_paths and item["category"] not in allowed_categories]
    if unexpected_paths:
        reasons.append("actual paths exceed the authorized expected surface: " + ", ".join(sorted(unexpected_paths)))
    if unexpected_components:
        reasons.append("actual components exceed the declared component boundary: " + ", ".join(unexpected_components))
    if unexpected_sensitive:
        reasons.append("actual sensitive dimensions exceed the declared surface: " + ", ".join(unexpected_sensitive))
    if risk_escalated:
        reasons.append("actual risk exceeds the expected risk context")
    if blast_escalated:
        reasons.append("actual blast radius exceeds the expected blast-radius context")

    signal = "REVIEW_REQUIRED" if reasons else "PASS"
    return _result(expected_identity, signal, reasons, expected_meta["digest"], actual_meta["digest"], {
        "revision": actual_meta["revision"],
        "authority_ref": expected_meta["authority"],
        "changed_paths": deepcopy(changed_paths),
    })


def _result(identity: Mapping[str, str], signal: str, reasons: list[str], expected_digest: str | None = None, actual_digest: str | None = None, observation: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": "change-surface-verification.v1",
        "signal": signal,
        "authoritative": False,
        "identity": dict(identity),
        "reasons": list(reasons) or ["actual surface is within the authorized expected interpretation"],
    }
    if expected_digest is not None:
        result["expected_digest"] = expected_digest
    if actual_digest is not None:
        result["actual_digest"] = actual_digest
    if observation is not None:
        result["observation"] = observation
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(result), key=lambda error: list(error.path))
    if errors:
        raise ChangeSurfaceVerificationError(f"internal signal is invalid: {errors[0].message}")
    return result
