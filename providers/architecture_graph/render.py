"""Deterministic SVG rendering for architecture graph artifacts."""

from __future__ import annotations

from html import escape
from typing import Any


class ArchitectureSvgRenderer:
    """Render semantic graph data without consuming provider-specific layout."""

    def render_graph(self, graph: dict[str, Any]) -> str:
        self._require_graph(graph)
        nodes = sorted(graph["nodes"], key=lambda node: node["id"])
        positions = self._positions(nodes)
        columns = min(3, max(1, len(nodes)))
        width = max(760, columns * 250 + 40)
        height = max(220, ((len(nodes) + columns - 1) // columns) * 120 + 100)
        parts = [self._header(width, height, graph["title"])]
        for edge in sorted(graph["edges"], key=lambda item: item["id"]):
            source = positions[edge["from"]]
            target = positions[edge["to"]]
            parts.append(
                f'<line x1="{source[0] + 90}" y1="{source[1] + 32}" x2="{target[0] + 90}" y2="{target[1] + 32}" '
                'stroke="#64748b" stroke-width="2" marker-end="url(#arrow)" />'
            )
            if edge.get("label"):
                x = (source[0] + target[0]) // 2 + 90
                y = (source[1] + target[1]) // 2 + 24
                parts.append(f'<text x="{x}" y="{y}" class="edge-label">{escape(edge["label"])}</text>')
        for node in nodes:
            x, y = positions[node["id"]]
            parts.append(f'<g data-node-id="{escape(node["id"])}">')
            parts.append(f'<rect x="{x}" y="{y}" width="180" height="64" rx="8" class="node" />')
            parts.append(f'<text x="{x + 12}" y="{y + 27}" class="node-kind">{escape(node["kind"])}</text>')
            parts.append(f'<text x="{x + 12}" y="{y + 48}" class="node-label">{escape(node["label"])}</text>')
            parts.append("</g>")
        parts.append("</svg>")
        return "".join(parts)

    def render_delta(self, delta: dict[str, Any]) -> str:
        if delta.get("schema") != "architecture-delta.v1":
            raise ValueError("expected architecture-delta.v1")
        sections = [
            ("ADDED", delta["added_nodes"], "#166534"),
            ("REMOVED", delta["removed_nodes"], "#991b1b"),
            ("CHANGED", [item["id"] for item in delta["changed_nodes"]], "#92400e"),
        ]
        sections.extend([
            ("ADDED EDGES", delta["added_edges"], "#166534"),
            ("REMOVED EDGES", delta["removed_edges"], "#991b1b"),
            ("CHANGED EDGES", [item["id"] for item in delta["changed_edges"]], "#92400e"),
        ])
        width, row_height = 760, 34
        height = 80 + sum(row_height * max(1, len(items)) for _, items, _ in sections)
        parts = [self._header(width, height, f"Architecture delta: {delta['graph_id']}")]
        y = 82
        for heading, items, color in sections:
            parts.append(f'<text x="28" y="{y}" class="delta-heading" fill="{color}">{heading}</text>')
            y += 22
            for item in sorted(items):
                parts.append(f'<text x="48" y="{y}" class="delta-item">{escape(item)}</text>')
                y += row_height
            if not items:
                parts.append('<text x="48" y="%d" class="delta-item">none</text>' % y)
                y += row_height
        parts.append("</svg>")
        return "".join(parts)

    @staticmethod
    def _require_graph(graph: dict[str, Any]) -> None:
        if graph.get("schema") != "architecture-graph.v1":
            raise ValueError("expected architecture-graph.v1")
        ids = {node["id"] for node in graph["nodes"]}
        if any(edge["from"] not in ids or edge["to"] not in ids for edge in graph["edges"]):
            raise ValueError("graph contains a dangling edge")

    @staticmethod
    def _positions(nodes: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
        return {node["id"]: (40 + (index % 3) * 240, 70 + (index // 3) * 120) for index, node in enumerate(nodes)}

    @staticmethod
    def _header(width: int, height: int, title: str) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><title>{escape(title)}</title>'
            '<style>.node{fill:#f8fafc;stroke:#334155}.node-kind{font:11px sans-serif;fill:#64748b}.node-label{font:14px sans-serif;fill:#0f172a}.edge-label,.delta-item{font:12px sans-serif;fill:#475569}.delta-heading{font:bold 14px sans-serif}</style>'
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#64748b"/></marker></defs>'
        )
