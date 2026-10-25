"""Validation and loading of explicit Humanizer project profiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from adapters.humanizer_python_rules import rename_python_lambda_parameter


class HumanizerProfileError(ValueError):
    """Raised when a Humanizer profile is missing, malformed, or unsafe."""


@dataclass(frozen=True)
class HumanizerProfile:
    profile_id: str
    language: str
    reference_set: tuple[str, ...]
    allowed_transformations: tuple[str, ...]
    parameters: dict[str, Any]


def load_humanizer_profile(path: Path | str) -> HumanizerProfile:
    """Load one explicit profile without enabling or executing it."""
    profile_path = Path(path)
    try:
        payload = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise HumanizerProfileError(f"cannot read Humanizer profile: {exc}") from exc
    if not isinstance(payload, dict):
        raise HumanizerProfileError("Humanizer profile must be an object")
    if payload.get("schema") != "humanizer-project-profile.v1":
        raise HumanizerProfileError("unsupported Humanizer profile schema")
    if payload.get("status") not in {"approved-fixture-profile", "approved-project-profile"}:
        raise HumanizerProfileError("Humanizer profile is not approved")
    profile_id = payload.get("profile_id")
    language = payload.get("language")
    reference_set = payload.get("reference_set")
    transformations = payload.get("allowed_transformations")
    parameters = payload.get("parameters", {})
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise HumanizerProfileError("profile_id is required")
    if not isinstance(language, str) or not language.strip():
        raise HumanizerProfileError("language is required")
    if not isinstance(reference_set, list) or not reference_set:
        raise HumanizerProfileError("reference_set must contain at least one path")
    if not all(isinstance(ref, str) and ref and not ref.startswith("/") and ".." not in PurePosixPath(ref).parts for ref in reference_set):
        raise HumanizerProfileError("reference_set paths must be relative and traversal-free")
    if not isinstance(transformations, list) or len(set(transformations)) != len(transformations):
        raise HumanizerProfileError("allowed_transformations must be a unique list")
    if not all(isinstance(rule, str) and rule.strip() for rule in transformations):
        raise HumanizerProfileError("allowed_transformations must contain non-empty strings")
    if not isinstance(parameters, dict):
        raise HumanizerProfileError("parameters must be an object")
    return HumanizerProfile(
        profile_id=profile_id,
        language=language,
        reference_set=tuple(reference_set),
        allowed_transformations=tuple(transformations),
        parameters=dict(parameters),
    )


def build_rules_for_profile(profile: HumanizerProfile) -> dict[str, Any]:
    """Build only the explicit transformations allowlisted by a profile."""
    rules: dict[str, Any] = {}
    if "rename-lambda-parameter" in profile.allowed_transformations:
        old = profile.parameters.get("old")
        new = profile.parameters.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            raise HumanizerProfileError(
                "rename-lambda-parameter requires string old and new parameters"
            )

        def rename(source: str) -> str:
            return rename_python_lambda_parameter(source, old=old, new=new)

        rules["rename-lambda-parameter"] = rename
    unknown = set(profile.allowed_transformations) - set(rules)
    if unknown:
        raise HumanizerProfileError(f"unsupported Humanizer transformations: {sorted(unknown)}")
    return rules
