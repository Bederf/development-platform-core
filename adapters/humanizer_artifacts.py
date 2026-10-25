"""Immutable persistence and fail-closed adoption checks for Humanizer artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .humanizer import HumanizerBundle


class HumanizerArtifactError(ValueError):
    """Raised when an artifact cannot be safely persisted or evaluated."""


@dataclass(frozen=True)
class StoredHumanizerArtifacts:
    root: Path
    candidate_path: Path
    manifest_path: Path
    forge_request_path: Path
    content_path: Path


class HumanizerArtifactStore:
    """Persist one Humanizer bundle beneath an approved root without overwrite."""

    def __init__(self, approved_root: Path | str) -> None:
        self.root = Path(approved_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def persist(self, bundle: HumanizerBundle) -> StoredHumanizerArtifacts:
        request_id = bundle.candidate.get("request_id")
        if not isinstance(request_id, str) or not request_id or Path(request_id).name != request_id:
            raise HumanizerArtifactError("request_id must be a single safe path component")
        target = self.root / request_id
        if target.exists():
            raise HumanizerArtifactError("Humanizer artifact already exists; refusing overwrite")

        temporary = Path(tempfile.mkdtemp(prefix=f".{request_id}-", dir=self.root))
        try:
            files = {
                "candidate.json": bundle.candidate,
                "manifest.json": bundle.manifest,
                "forge-request.json": bundle.forge_request,
            }
            for name, payload in files.items():
                (temporary / name).write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            (temporary / "candidate-content").write_text(bundle.candidate_content, encoding="utf-8")
            for path in temporary.iterdir():
                os.chmod(path, 0o600)
            os.rename(temporary, target)
        except OSError as exc:
            if temporary.exists():
                for path in temporary.iterdir():
                    path.unlink()
                temporary.rmdir()
            raise HumanizerArtifactError(f"could not persist Humanizer artifacts: {exc}") from exc
        return StoredHumanizerArtifacts(
            root=target,
            candidate_path=target / "candidate.json",
            manifest_path=target / "manifest.json",
            forge_request_path=target / "forge-request.json",
            content_path=target / "candidate-content",
        )


@dataclass(frozen=True)
class HumanizerAdoptionDecision:
    status: str
    reason: str


def assess_humanizer_adoption(
    candidate: Mapping[str, Any],
    verification_result: Mapping[str, Any],
) -> HumanizerAdoptionDecision:
    """Allow only a fully verified candidate to proceed to human review."""
    if candidate.get("schema") != "code-humanizer.v1":
        return HumanizerAdoptionDecision("blocked", "invalid Humanizer candidate")
    if verification_result.get("schema") != "verification-result.v1":
        return HumanizerAdoptionDecision("blocked", "invalid verification result")
    verification_ref = candidate.get("verification", {}).get("verification_request_ref")
    if verification_result.get("request_id") != verification_ref:
        return HumanizerAdoptionDecision("blocked", "verification result is not bound to candidate")
    if verification_result.get("status") != "PASSED":
        return HumanizerAdoptionDecision("blocked", "Forge verification did not pass")
    required = {"semantic_integrity", "lint", "tests"}
    checks = verification_result.get("checks", [])
    passed = {check.get("check_id") for check in checks if check.get("status") == "PASSED"}
    if not required.issubset(passed):
        return HumanizerAdoptionDecision("blocked", "required Forge checks are incomplete")
    return HumanizerAdoptionDecision("eligible_for_human_review", "Forge checks passed; explicit review remains required")
