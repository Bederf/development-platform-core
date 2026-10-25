"""Provider-neutral capability projection planning.

The planner describes how a Core-owned capability may be handed to a harness.
It deliberately does not install files, activate clients, start MCP servers,
or grant authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CapabilityProjectionError(ValueError):
    """Raised when a projection plan cannot be represented safely."""


def build_skill_projection_plan(
    *,
    projection_id: str,
    capability_id: str,
    capability_version: str,
    source_path: str | Path,
    core_skill_root: str | Path,
    source_identity: str,
    harness_id: str,
    adapter_id: str,
    adapter_version: str,
    target_kind: str | None = None,
    target_reference: str | None = None,
    status: str = "planned",
) -> dict[str, Any]:
    """Build a typed plan without performing projection or activation."""

    if not projection_id.strip() or not capability_id.strip() or not capability_version.strip():
        raise CapabilityProjectionError("projection and capability identity are required")
    if not source_identity.strip():
        raise CapabilityProjectionError("source_identity is required")
    if status not in {"discovered", "planned", "unavailable", "verified"}:
        raise CapabilityProjectionError(f"unsupported projection status: {status!r}")
    source = Path(source_path).expanduser().resolve()
    root = Path(core_skill_root).expanduser().resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise CapabilityProjectionError("capability source must be inside the Core skill root") from exc
    if not source.is_file():
        raise CapabilityProjectionError(f"capability source is unavailable: {source}")
    if target_kind is None or target_reference is None:
        target = None
        activation_policy = "consumer_managed"
    else:
        if target_kind not in {"skill_root", "prompt_input", "plugin_registry", "mcp_registry"}:
            raise CapabilityProjectionError(f"unsupported projection target: {target_kind!r}")
        if not target_reference.strip():
            raise CapabilityProjectionError("target_reference is required when target_kind is set")
        target = {"kind": target_kind, "reference": target_reference}
        activation_policy = "explicit_adapter_action"
    return {
        "schema": "capability-projection.v1",
        "projection_id": projection_id,
        "capability": {
            "semantic_type": "capability_definition",
            "id": capability_id,
            "version": capability_version,
        },
        "source": {"kind": "skill", "path": str(source), "content_identity": source_identity},
        "harness": {"harness_id": harness_id, "adapter_id": adapter_id, "adapter_version": adapter_version},
        "target": target,
        "status": status,
        "activation_policy": activation_policy,
        "provenance": {
            "source_reference": str(source),
            "source_digest": source_identity,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
