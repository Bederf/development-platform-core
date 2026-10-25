from __future__ import annotations

import pytest

from adapters.radix.workflow_routing import WorkflowRoutingError, require_active_provider, resolve_gsd_workflow_routing


def capabilities(workflow_providers: dict | None = None) -> dict:
    return {
        "selections": {
            "gsd": {
                "enabled": True,
                "configuration": {"workflow_providers": workflow_providers or {}},
            }
        }
    }


def test_unspecified_stages_route_to_native_gsd() -> None:
    routing = resolve_gsd_workflow_routing(capabilities())
    assert routing["status"] == "ready"
    assert require_active_provider(routing, "PLAN")["provider"] == "native-gsd"


def test_native_gsd_remains_operational_without_spec_kit() -> None:
    routing = resolve_gsd_workflow_routing(capabilities())
    assert all(stage["provider"] == "native-gsd" for stage in routing["stages"].values())
    assert all(stage["activation"] == "allowed" for stage in routing["stages"].values())


def test_approved_spec_kit_selection_is_active() -> None:
    routing = resolve_gsd_workflow_routing(
        capabilities({"SPECIFICATION": {"provider": "spec-kit", "version": "1.0.4", "readiness": "ready"}})
    )
    assert routing["status"] == "ready"
    assert routing["stages"]["SPECIFICATION"]["activation"] == "allowed"
    assert require_active_provider(routing, "SPECIFICATION")["provider"] == "spec-kit"


def test_mixed_routing_keeps_native_stages_active() -> None:
    routing = resolve_gsd_workflow_routing(
        capabilities({"SPECIFICATION": {"provider": "spec-kit", "version": "1.0.4", "readiness": "ready"}})
    )
    assert require_active_provider(routing, "IMPLEMENTATION")["provider"] == "native-gsd"


def test_tampered_provider_metadata_fails_closed() -> None:
    with pytest.raises(WorkflowRoutingError, match="not registered"):
        resolve_gsd_workflow_routing(
            capabilities({"PLAN": {"provider": "spec-kit", "version": "1.0.4", "readiness": "conformance-only"}})
        )


def test_disabled_gsd_cannot_route_workflow() -> None:
    with pytest.raises(WorkflowRoutingError, match="not enabled"):
        resolve_gsd_workflow_routing({"selections": {"gsd": {"enabled": False}}})
