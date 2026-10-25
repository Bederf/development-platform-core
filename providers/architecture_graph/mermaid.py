"""Read-only projection of a Mermaid flowchart into architecture-graph.v1."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MermaidProjectionProvider:
    """Project an explicit Mermaid ``graph`` block without executing it."""

    def __init__(self, *, source_path: str | Path, project_id: str, graph_id: str, graph_version: str = "1.0.0"):
        self.source_path = Path(source_path)
        self.project_id = project_id
        self.graph_id = graph_id
        self.graph_version = graph_version

    def project(self, *, revision: str | None = None) -> dict[str, Any]:
        try:
            text = self.source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"unable to read Mermaid source: {self.source_path}") from exc
        lines = text.splitlines()
        start = next((index for index, line in enumerate(lines) if re.match(r"^\s*graph\s+(TB|TD|LR|RL|BT)\s*$", line)), None)
        if start is None:
            raise ValueError("no supported Mermaid graph block found")
        end = next((index for index in range(start + 1, len(lines)) if lines[index].strip() == "```"), len(lines))
        digest = f"sha256:{hashlib.sha256(self.source_path.read_bytes()).hexdigest()}"
        effective_revision = revision or self._git_revision()
        source_ref = {"path": self.source_path.name, "revision": effective_revision, "line_start": start + 1, "line_end": end}
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        limitations: list[str] = []
        for line_number, raw_line in enumerate(lines[start + 1:end], start=start + 2):
            line = raw_line.strip()
            if not line or line in ("end",) or line.startswith("class") or line.startswith("classDef"):
                continue
            for match in re.finditer(r"([A-Za-z][A-Za-z0-9_]*)\s*(?:\(([^)]*)\)|\[([^]]*)\]|\{([^}]*)\})", line):
                node_id, round_label, square_label, brace_label = match.groups()
                label = round_label or square_label or brace_label or node_id
                nodes.setdefault(node_id, self._node(node_id, label, source_ref))
            edge_match = re.search(r"([A-Za-z][A-Za-z0-9_]*)(?:\s*(?:\([^)]*\)|\[[^]]*\]|\{[^}]*\}))?\s*-->(?:\|([^|]*)\|)?\s*([A-Za-z][A-Za-z0-9_]*)(?:\s*(?:\([^)]*\)|\[[^]]*\]|\{[^}]*\}))?", line)
            if edge_match:
                from_id, label, to_id = edge_match.groups()
                nodes.setdefault(from_id, self._node(from_id, from_id, source_ref))
                nodes.setdefault(to_id, self._node(to_id, to_id, source_ref))
                edges.append({"id": f"{from_id.lower()}-{to_id.lower()}-{len(edges) + 1}", "from": from_id.lower(), "to": to_id.lower(), "relationship": label or "relates_to", "label": label, "source_refs": [dict(source_ref)]})
            elif line.startswith("subgraph"):
                match = re.match(r"subgraph\s+([A-Za-z][A-Za-z0-9_]*)\[\"([^\"]+)\"\]", line)
                if match:
                    group_id, label = match.groups()
                    nodes.setdefault(group_id, {"id": group_id.lower(), "kind": "group", "label": label, "status": "defined", "source_refs": [dict(source_ref)]})
                else:
                    limitations.append(f"unparsed Mermaid subgraph at line {line_number}")
        normalized_nodes = []
        for node in nodes.values():
            node["id"] = node["id"].lower()
            normalized_nodes.append(node)
        normalized_edges = []
        for edge in edges:
            edge["from"] = edge["from"].lower()
            edge["to"] = edge["to"].lower()
            normalized_edges.append(edge)
        node_ids = {node["id"] for node in normalized_nodes}
        if any(edge["from"] not in node_ids or edge["to"] not in node_ids for edge in normalized_edges):
            raise ValueError("Mermaid edge references an unparsed node")
        graph_payload = {"nodes": normalized_nodes, "edges": normalized_edges}
        graph_digest = json.dumps(graph_payload, sort_keys=True, separators=(",", ":")).encode()
        return {
            "schema": "architecture-graph.v1", "graph_id": self.graph_id, "graph_version": self.graph_version,
            "project_id": self.project_id, "title": self.source_path.stem, "purpose": "Read-only semantic projection from an approved Mermaid architecture source",
            "status": "validated", "source": {"kind": "document_set", "revision": effective_revision, "references": [source_ref]},
            "generated_at": datetime.now(timezone.utc).isoformat(), "nodes": normalized_nodes, "edges": normalized_edges,
            "limitations": limitations + ["Mermaid layout, styling, and sequence diagrams are not interpreted as runtime behavior."],
            "digest": f"sha256:{hashlib.sha256(graph_digest).hexdigest()}",
        }

    @staticmethod
    def _node(node_id: str, label: str, source_ref: dict[str, Any]) -> dict[str, Any]:
        clean_label = re.sub(r"<br\s*/?>", " ", label).strip() or node_id
        return {"id": node_id.lower(), "kind": "component", "label": clean_label, "status": "defined", "source_refs": [dict(source_ref)]}

    def _git_revision(self) -> str | None:
        return None
