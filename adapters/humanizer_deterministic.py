"""Conservative deterministic Humanizer provider.

This provider is the safe baseline implementation. Without an explicitly
qualified project reference profile, it returns the source unchanged and
records that no transformation was authorized. It is useful for proving the
candidate, hashing, manifest, and Forge handoff path without inventing a
universal coding style.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ConservativeHumanizerProvider:
    """Return an unchanged candidate when no qualified style rule is present."""

    def __call__(self, request: Mapping[str, Any]) -> dict[str, str]:
        target = request.get("target")
        source = request.get("source")
        if not isinstance(target, str) or not isinstance(source, str):
            raise ValueError("Humanizer request requires target and source")
        return {
            "candidate_content": source,
            "candidate_path": target,
            "transformation_manifest_ref": (
                f"artifacts/humanizer/{request.get('request_id', 'unknown')}/manifest.json"
            ),
            "rules_applied": [],
        }
