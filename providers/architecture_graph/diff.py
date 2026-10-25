"""Deterministic comparison for architecture-graph.v1 projections."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


class ArchitectureDeltaProvider:
    """Compute a stable semantic delta between two graph payloads."""

    def compare(self, before: dict[str, Any], after: dict[str, Any], *, delta_id: str) -> dict[str, Any]:
        if before.get("schema") != "architecture-graph.v1" or after.get("schema") != "architecture-graph.v1":
            raise ValueError("both inputs must be architecture-graph.v1 projections")
        if before.get("graph_id") != after.get("graph_id"):
            raise ValueError("cannot compare different graph IDs")

        nodes = self._compare_items(before["nodes"], after["nodes"])
        edges = self._compare_items(before["edges"], after["edges"])
        result: dict[str, Any] = {
            "schema": "architecture-delta.v1",
            "delta_id": delta_id,
            "graph_id": before["graph_id"],
            "before": self._ref(before),
            "after": self._ref(after),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "added_nodes": nodes["added"],
            "removed_nodes": nodes["removed"],
            "changed_nodes": nodes["changed"],
            "added_edges": edges["added"],
            "removed_edges": edges["removed"],
            "changed_edges": edges["changed"],
            "limitations": ["The delta compares authored graph projections; it does not establish runtime impact."],
        }
        digest_payload = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        result["digest"] = f"sha256:{hashlib.sha256(digest_payload).hexdigest()}"
        return result

    @staticmethod
    def _ref(graph: dict[str, Any]) -> dict[str, Any]:
        return {"graph_id": graph["graph_id"], "graph_version": graph["graph_version"], "digest": graph["digest"]}

    @staticmethod
    def _compare_items(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, list[Any]]:
        old = {item["id"]: item for item in before}
        new = {item["id"]: item for item in after}
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        changed = []
        for item_id in sorted(set(old) & set(new)):
            fields = []
            for field in sorted(set(old[item_id]) | set(new[item_id])):
                if field == "id" or old[item_id].get(field) == new[item_id].get(field):
                    continue
                fields.append({"field": field, "before": old[item_id].get(field), "after": new[item_id].get(field)})
            if fields:
                changed.append({"id": item_id, "changes": fields})
        return {"added": added, "removed": removed, "changed": changed}
