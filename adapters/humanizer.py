"""Provider-neutral execution boundary for the governed Humanizer capability.

The adapter accepts an injected transformation provider, constructs the
consumer-neutral ``code-humanizer.v1`` artifact, and delegates verification to
Forge. It never writes source files, approves a candidate, or activates a
Humanizer implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from .forge_request import ForgeRequestAdapter


class HumanizerAdapterError(ValueError):
    """Raised when a Humanizer provider result cannot cross the Core boundary."""


HumanizerProvider = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class HumanizerRequest:
    """Immutable input supplied to one bounded Humanizer transformation."""

    request_id: str
    target: str
    source: str
    profile: str | None = None
    aggression: float = 0.0


@dataclass(frozen=True)
class HumanizerBundle:
    """Candidate, transformation provenance, and unexecuted Forge request."""

    candidate: dict[str, Any]
    manifest: dict[str, Any]
    forge_request: dict[str, Any]
    candidate_content: str


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/"):
        return False
    path = PurePosixPath(value)
    return ".." not in path.parts and value != "."


class HumanizerAdapter:
    """Build and validate a proposal-only Humanizer artifact."""

    def __init__(self, provider: HumanizerProvider) -> None:
        self._provider = provider
        schema_path = Path(__file__).parents[1] / "contracts" / "code-humanizer.v1.schema.json"
        self._validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
        manifest_path = Path(__file__).parents[1] / "contracts" / "humanizer-transformation-manifest.v1.schema.json"
        self._manifest_validator = Draft202012Validator(json.loads(manifest_path.read_text(encoding="utf-8")))

    def transform(self, request: HumanizerRequest) -> dict[str, Any]:
        """Return a validated candidate artifact and Forge verification handoff."""
        return self._transform(request, self._provider(self._provider_input(request)))

    @staticmethod
    def _provider_input(request: HumanizerRequest) -> dict[str, Any]:
        return {
            "request_id": request.request_id,
            "target": request.target,
            "source": request.source,
            "profile": request.profile,
            "aggression": request.aggression,
        }

    def _transform(self, request: HumanizerRequest, raw: Mapping[str, Any]) -> dict[str, Any]:
        if not request.request_id.strip():
            raise HumanizerAdapterError("request_id is required")
        if not _valid_relative_path(request.target):
            raise HumanizerAdapterError("target must be a relative, traversal-free path")
        if not 0 <= request.aggression <= 1:
            raise HumanizerAdapterError("aggression must be between 0 and 1")

        if not isinstance(raw, Mapping):
            raise HumanizerAdapterError("Humanizer provider must return an object")
        content = raw.get("candidate_content")
        target = raw.get("candidate_path", request.target)
        manifest_ref = raw.get("transformation_manifest_ref")
        rules = raw.get("rules_applied", [])
        if not isinstance(content, str):
            raise HumanizerAdapterError("provider must return candidate_content")
        if not _valid_relative_path(target):
            raise HumanizerAdapterError("candidate_path must be a relative, traversal-free path")
        if not isinstance(manifest_ref, str) or not manifest_ref.strip():
            raise HumanizerAdapterError("provider must return transformation_manifest_ref")
        if not isinstance(rules, list) or not all(isinstance(rule, str) and rule.strip() for rule in rules):
            raise HumanizerAdapterError("rules_applied must be a list of non-empty strings")
        if len(set(rules)) != len(rules):
            raise HumanizerAdapterError("rules_applied must not contain duplicates")

        result: dict[str, Any] = {
            "schema": "code-humanizer.v1",
            "capability": "code-humanizer",
            "version": "1.0.0",
            "request_id": request.request_id,
            "action": {
                "capability": "code-humanizer",
                "target": request.target,
                "profile": request.profile,
                "aggression": request.aggression,
            },
            "acceptance": {
                "semantic_integrity": "required",
                "lint": "required",
                "tests": "required",
                "forge_verification": "required",
            },
            "artifact": {
                "candidate_artifact": {"path": target, "content_hash": _sha256(content)},
                "source_hash": _sha256(request.source),
                "candidate_hash": _sha256(content),
                "transformation_manifest": {"type": "artifact", "ref": manifest_ref},
            },
            "verification": {
                "delegated_to": "forge",
                "required_checks": ["semantic_integrity", "lint", "tests"],
                "verification_request_ref": None,
            },
        }
        errors = sorted(self._validator.iter_errors(result), key=lambda error: list(error.path))
        if errors:
            location = ".".join(str(part) for part in errors[0].path) or "result"
            raise HumanizerAdapterError(
                f"generated artifact failed schema validation at {location}: {errors[0].message}"
            )
        return result

    def transform_bundle(self, request: HumanizerRequest) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Return the candidate, provenance manifest, and exact candidate content."""
        raw = self._provider(self._provider_input(request))
        candidate = self._transform(request, raw)
        rules = raw.get("rules_applied", [])
        manifest = {
            "schema": "humanizer-transformation-manifest.v1",
            "request_id": request.request_id,
            "target": candidate["artifact"]["candidate_artifact"]["path"],
            "source_hash": candidate["artifact"]["source_hash"],
            "candidate_hash": candidate["artifact"]["candidate_hash"],
            "profile": request.profile,
            "aggression": request.aggression,
            "changed": request.source != raw.get("candidate_content"),
            "rules": rules,
        }
        errors = sorted(self._manifest_validator.iter_errors(manifest), key=lambda error: list(error.path))
        if errors:
            location = ".".join(str(part) for part in errors[0].path) or "manifest"
            raise HumanizerAdapterError(f"transformation manifest failed validation at {location}: {errors[0].message}")
        return candidate, manifest, raw["candidate_content"]

    def qualify_for_forge(
        self,
        request: HumanizerRequest,
        *,
        project_id: str,
        session_id: str | None = None,
    ) -> HumanizerBundle:
        """Construct a Humanizer candidate and typed Forge verification request."""
        candidate, manifest, candidate_content = self.transform_bundle(request)
        forge_request_id = f"forge-humanizer-verify:{request.request_id}"
        forge_request = ForgeRequestAdapter().build(
            operation="verify",
            project_id=project_id,
            request_id=forge_request_id,
            session_id=session_id,
            verification_request={
                "capability": "code-humanizer",
                "humanizer_request_id": request.request_id,
                "candidate_artifact": candidate["artifact"]["candidate_artifact"],
                "source_hash": candidate["artifact"]["source_hash"],
                "candidate_hash": candidate["artifact"]["candidate_hash"],
                "transformation_manifest": manifest,
                "required_checks": candidate["verification"]["required_checks"],
            },
        )
        candidate = deepcopy(candidate)
        candidate["verification"]["verification_request_ref"] = forge_request_id
        return HumanizerBundle(
            candidate=candidate,
            manifest=manifest,
            forge_request=forge_request,
            candidate_content=candidate_content,
        )
