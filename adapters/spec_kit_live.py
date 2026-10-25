"""Live, dependency-free bridge for importing Spec Kit project artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from .development_workflow import FakeDevelopmentWorkflowAdapter
from .spec_kit_mapping import SpecKitMappingError, map_operation


class SpecKitLiveAdapterError(ValueError):
    """Raised when a live Spec Kit artifact cannot be safely imported."""


class SpecKitLiveAdapter:
    """Translate real Spec Kit workspace files into Core proposals/reports."""

    def __init__(self, *, workspace: str | Path, provider_version: str = "1.0.4") -> None:
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise SpecKitLiveAdapterError("Spec Kit workspace must be an existing directory")
        if not provider_version.strip():
            raise SpecKitLiveAdapterError("provider_version is required")
        self.workspace = root
        self.provider_version = provider_version.strip()
        self.core = FakeDevelopmentWorkflowAdapter(provider_ref=f"spec-kit@{self.provider_version}")

    def _artifact_path(self, artifact_path: str | Path) -> Path:
        candidate = (self.workspace / Path(artifact_path)).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise SpecKitLiveAdapterError("artifact_path must remain inside the Spec Kit workspace") from exc
        if not candidate.is_file():
            raise SpecKitLiveAdapterError("Spec Kit artifact is missing or is not a regular file")
        return candidate

    def import_artifact(
        self,
        operation: str,
        *,
        artifact_ref: str,
        artifact_path: str | Path,
        input_refs: Sequence[str] = (),
        supersedes_ref: str | None = None,
        requirements_complete: bool | None = None,
    ) -> dict[str, Any]:
        """Import one provider artifact and emit a Core-shaped result."""

        try:
            mapping = map_operation(operation)
        except SpecKitMappingError as exc:
            raise SpecKitLiveAdapterError(str(exc)) from exc
        if mapping["stage"] in {"VERIFICATION", "ACCEPTANCE"}:
            raise SpecKitLiveAdapterError(f"Spec Kit cannot perform {mapping['stage'].lower()}")

        path = self._artifact_path(artifact_path)
        content = path.read_bytes()
        if not content:
            raise SpecKitLiveAdapterError("Spec Kit artifact must not be empty")
        digest = f"sha256:{sha256(content).hexdigest()}"
        refs = list(input_refs)
        provenance = {
            "provider": "spec-kit",
            "provider_version": self.provider_version,
            "operation": operation,
            "artifact_path": path.relative_to(self.workspace).as_posix(),
            "content_digest": digest,
        }

        key = operation.strip().lower()
        if key in {"/implement", "/speckit.implement"}:
            if not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
                raise SpecKitLiveAdapterError("implementation import requires input task references")
            result = self.core.report_implementation(
                artifact_ref=artifact_ref, task_refs=refs, digest=digest
            )
        elif key in {"/converge", "/speckit.converge"}:
            if requirements_complete is None:
                raise SpecKitLiveAdapterError("convergence import requires requirements_complete")
            result = self.core.assess_convergence(
                artifact_ref=artifact_ref,
                requirements_complete=requirements_complete,
                evidence_refs=refs or [artifact_ref],
            )
        else:
            result = {
                "operation": operation,
                "mapping": mapping,
                "proposal": self.core.propose_artifact(
                    artifact_ref=artifact_ref,
                    kind=mapping["artifact_kind"],
                    stage=mapping["stage"],
                    digest=digest,
                    supersedes_ref=supersedes_ref,
                ),
            }
        result["provider_provenance"] = provenance
        result["input_refs"] = refs
        return result
