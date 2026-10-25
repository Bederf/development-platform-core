"""Project an Obsidian Canvas into the neutral architecture-graph.v1 shape.

The Canvas remains consumer-owned. This provider only reads the explicitly
supplied file; it does not infer runtime behavior, resolve linked documents,
or preserve renderer-controlled coordinates.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CanvasProjectionError(ValueError):
    """Raised when a Canvas cannot be projected safely."""


class CanvasProjectionProvider:
    """Read one declared Canvas and emit an architecture graph projection."""

    def __init__(self, *, canvas_path: str | Path, project_id: str, graph_id: str, graph_version: str = "1.0.0", source_root: str | Path | None = None):
        self.canvas_path = Path(canvas_path)
        self.project_id = project_id
        self.graph_id = graph_id
        self.graph_version = graph_version
        self.source_root = Path(source_root) if source_root is not None else self.canvas_path.parent

    def project(self, *, revision: str | None = None) -> dict[str, Any]:
        try:
            payload = json.loads(self.canvas_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CanvasProjectionError(f"unable to read Canvas: {self.canvas_path}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list) or not isinstance(payload.get("edges"), list):
            raise CanvasProjectionError("Canvas must contain nodes and edges arrays")

        digest = f"sha256:{hashlib.sha256(self.canvas_path.read_bytes()).hexdigest()}"
        effective_revision = revision if revision is not None else self._git_revision()
        canvas_ref = {"path": self.canvas_path.name, "revision": effective_revision, "digest": digest}
        limitations: list[str] = []
        nodes = [self._node(node, canvas_ref, limitations) for node in payload["nodes"]]
        edges = [self._edge(edge, canvas_ref) for edge in payload["edges"]]
        references = [canvas_ref]
        seen_references = {(canvas_ref["path"], canvas_ref.get("anchor"))}
        for node in nodes:
            for reference in node["source_refs"]:
                key = (reference["path"], reference.get("anchor"))
                if key not in seen_references:
                    references.append(reference)
                    seen_references.add(key)
        node_ids = {node["id"] for node in nodes}
        if len(node_ids) != len(nodes):
            raise CanvasProjectionError("Canvas node IDs must be unique")
        if any(edge["from"] not in node_ids or edge["to"] not in node_ids for edge in edges):
            raise CanvasProjectionError("Canvas edges must reference existing nodes")

        return {
            "schema": "architecture-graph.v1",
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "project_id": self.project_id,
            "title": self.canvas_path.stem,
            "purpose": "Read-only semantic projection from an Obsidian Canvas",
            "status": "validated",
            "source": {"kind": "canvas", "revision": effective_revision, "references": references},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "nodes": nodes,
            "edges": edges,
            "limitations": limitations + [
                "Canvas layout, styling, and freeform placement are not semantic architecture claims.",
                "Linked document contents are resolved only when they are local files under the declared source root.",
            ],
            "digest": f"sha256:{hashlib.sha256(json.dumps({'nodes': nodes, 'edges': edges}, sort_keys=True).encode()).hexdigest()}",
        }

    def _node(self, node: Any, canvas_ref: dict[str, Any], limitations: list[str]) -> dict[str, Any]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise CanvasProjectionError("every Canvas node requires a string id")
        node_type = node.get("type")
        kind = {"file": "document", "group": "group", "text": "other"}.get(node_type, "other")
        label = node.get("label") or node.get("file")
        if not label and isinstance(node.get("text"), str):
            label = node["text"].strip().splitlines()[0].lstrip("# ") or node["id"]
        if not isinstance(label, str) or not label:
            label = node["id"]
        source_ref = dict(canvas_ref)
        if isinstance(node.get("subpath"), str):
            source_ref["anchor"] = node["subpath"]
        if node_type == "file" and isinstance(node.get("file"), str):
            resolved = self._resolve_file(node["file"], node.get("subpath"), limitations)
            if resolved is not None:
                source_ref = resolved
        return {"id": node["id"], "kind": kind, "label": label, "status": "defined", "source_refs": [source_ref]}

    def _resolve_file(self, relative_path: str, subpath: Any, limitations: list[str]) -> dict[str, Any] | None:
        candidate = (self.source_root / relative_path).resolve()
        root = self.source_root.resolve()
        if root != candidate and root not in candidate.parents:
            limitations.append(f"source outside declared root: {relative_path}")
            return None
        if not candidate.is_file():
            limitations.append(f"source not found: {relative_path}")
            return None
        lines = candidate.read_text(encoding="utf-8").splitlines()
        anchor = subpath if isinstance(subpath, str) else None
        line_start, line_end = self._heading_range(lines, anchor)
        result: dict[str, Any] = {
            "path": str(candidate.relative_to(root)),
            "revision": self._git_revision(candidate.parent),
            "digest": f"sha256:{hashlib.sha256(candidate.read_bytes()).hexdigest()}",
        }
        if anchor is not None:
            result["anchor"] = anchor
        if line_start is not None:
            result["line_start"] = line_start
            result["line_end"] = line_end
        return result

    @staticmethod
    def _heading_range(lines: list[str], anchor: str | None) -> tuple[int | None, int | None]:
        if not anchor or not anchor.startswith("#"):
            return None, None
        heading = anchor.lstrip("# ").strip().casefold()
        starts = [(index, line.lstrip("# ").strip().casefold(), len(line) - len(line.lstrip("#"))) for index, line in enumerate(lines)]
        match = next(((index, level) for index, text, level in starts if text == heading), None)
        if match is None:
            return None, None
        start, level = match
        end = len(lines)
        for index, _, other_level in starts[start + 1:]:
            if other_level and other_level <= level:
                end = index
                break
        return start + 1, end

    def _git_revision(self, cwd: Path | None = None) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd or self.canvas_path.parent), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip() or None

    def _edge(self, edge: Any, canvas_ref: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(edge, dict) or not all(isinstance(edge.get(key), str) for key in ("id", "fromNode", "toNode")):
            raise CanvasProjectionError("every Canvas edge requires id, fromNode, and toNode")
        label = edge.get("label") if isinstance(edge.get("label"), str) else None
        return {
            "id": edge["id"],
            "from": edge["fromNode"],
            "to": edge["toNode"],
            "relationship": label or "relates_to",
            "label": label,
            "source_refs": [dict(canvas_ref)],
        }
