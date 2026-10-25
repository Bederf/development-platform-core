"""In-memory Spec Kit-shaped provider for adapter conformance.

The fixture models provider operations without installing or invoking Spec Kit.
It delegates contract-shaped proposal validation to the Core fake adapter.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .development_workflow import FakeDevelopmentWorkflowAdapter
from .spec_kit_mapping import SpecKitMappingError, map_operation


class FakeSpecKitProvider:
    """Side-effect-free provider fixture that can only make Core proposals."""

    def __init__(self) -> None:
        self.core = FakeDevelopmentWorkflowAdapter(provider_ref="fake-spec-kit")

    def emit(
        self,
        operation: str,
        *,
        artifact_ref: str,
        digest: str,
        task_refs: Sequence[str] = (),
        requirements_complete: bool | None = None,
        evidence_refs: Sequence[str] = (),
        supersedes_ref: str | None = None,
    ) -> dict[str, Any]:
        """Translate one supported provider operation into a Core proposal."""

        operation_key = operation.strip().lower()
        mapping = map_operation(operation_key)
        if mapping["stage"] in {"VERIFICATION", "ACCEPTANCE"}:
            raise SpecKitMappingError(f"Spec Kit cannot perform {mapping['stage'].lower()}")
        refs = list(evidence_refs) or [artifact_ref]
        if operation_key in {"/implement", "/speckit.implement"}:
            return self.core.report_implementation(
                artifact_ref=artifact_ref, task_refs=task_refs, digest=digest
            )
        if operation_key in {"/converge", "/speckit.converge"}:
            if requirements_complete is None:
                raise SpecKitMappingError("/converge requires requirements_complete")
            return self.core.assess_convergence(
                artifact_ref=artifact_ref,
                requirements_complete=requirements_complete,
                evidence_refs=refs,
            )
        proposal = self.core.propose_artifact(
            artifact_ref=artifact_ref,
            kind=mapping["artifact_kind"],
            stage=mapping["stage"],
            digest=digest,
            supersedes_ref=supersedes_ref,
        )
        return {"operation": operation, "mapping": mapping, "proposal": proposal}
