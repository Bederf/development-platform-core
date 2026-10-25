"""Resolve GSD workflow providers from Radix capability selections."""

from __future__ import annotations

from typing import Any

from .capabilities import WORKFLOW_PROVIDER_REGISTRY, WORKFLOW_STAGES


class WorkflowRoutingError(ValueError):
    """Raised when a workflow provider cannot be safely activated."""


def resolve_gsd_workflow_routing(capabilities: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic stage routing without invoking any provider."""

    selections = capabilities.get("selections")
    gsd = selections.get("gsd") if isinstance(selections, dict) else None
    if not isinstance(gsd, dict) or gsd.get("enabled") is not True:
        raise WorkflowRoutingError("GSD capability is not enabled")

    configured = gsd.get("configuration", {}).get("workflow_providers", {})
    if not isinstance(configured, dict):
        raise WorkflowRoutingError("GSD workflow provider configuration is invalid")
    stages: dict[str, dict[str, str]] = {}
    for stage in sorted(WORKFLOW_STAGES):
        selection = configured.get(stage)
        if selection is None:
            provider = "native-gsd"
            version = WORKFLOW_PROVIDER_REGISTRY[provider]["version"]
            readiness = WORKFLOW_PROVIDER_REGISTRY[provider]["readiness"]
        elif isinstance(selection, dict):
            provider = selection.get("provider")
            version = selection.get("version")
            readiness = selection.get("readiness")
            registered = WORKFLOW_PROVIDER_REGISTRY.get(provider)
            if registered is None or version != registered["version"] or readiness != registered["readiness"]:
                raise WorkflowRoutingError(f"workflow provider selection is not registered: {stage}")
        else:
            raise WorkflowRoutingError(f"workflow provider selection is invalid: {stage}")
        stages[stage] = {
            "provider": provider,
            "version": version,
            "readiness": readiness,
            "activation": "allowed" if readiness == "ready" else "blocked",
        }
    return {
        "schema": "development-workflow-provider-routing.v1",
        "orchestrator": "gsd.master",
        "status": "ready" if all(item["activation"] == "allowed" for item in stages.values()) else "blocked",
        "stages": stages,
    }


def require_active_provider(routing: dict[str, Any], stage: str) -> dict[str, str]:
    """Return an active provider or fail closed for an unqualified provider."""

    stages = routing.get("stages")
    selection = stages.get(stage) if isinstance(stages, dict) else None
    if not isinstance(selection, dict):
        raise WorkflowRoutingError(f"workflow stage is not routable: {stage}")
    if selection.get("activation") != "allowed":
        raise WorkflowRoutingError(
            f"workflow provider is not qualified for {stage}: {selection.get('provider')}"
        )
    return dict(selection)
