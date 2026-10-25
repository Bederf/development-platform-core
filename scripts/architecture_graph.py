#!/usr/bin/env python3
"""Generate derived architecture artifacts from an explicit Canvas source."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from providers.architecture_graph import ArchitectureDeltaProvider, ArchitectureSvgRenderer, CanvasProjectionProvider, MermaidProjectionProvider


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--canvas", type=Path)
    source.add_argument("--mermaid", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--graph-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--baseline", type=Path, default=None, help="previous architecture-graph.json to compare")
    parser.add_argument("--revision", default=None)
    args = parser.parse_args()

    if args.canvas is not None:
        graph = CanvasProjectionProvider(
            canvas_path=args.canvas,
            project_id=args.project,
            graph_id=args.graph_id,
            source_root=args.source_root,
        ).project(revision=args.revision)
    else:
        graph = MermaidProjectionProvider(
            source_path=args.mermaid,
            project_id=args.project,
            graph_id=args.graph_id,
        ).project(revision=args.revision)
    renderer = ArchitectureSvgRenderer()
    graph_bytes = (json.dumps(graph, indent=2, sort_keys=True) + "\n").encode()
    svg_bytes = renderer.render_graph(graph).encode()
    args.output.mkdir(parents=True, exist_ok=True)
    graph_path = args.output / "architecture-graph.json"
    svg_path = args.output / "architecture.svg"
    graph_path.write_bytes(graph_bytes)
    svg_path.write_bytes(svg_bytes)
    artifacts = [
        {"kind": "graph", "path": graph_path.name, "digest": _digest(graph_bytes)},
        {"kind": "svg", "path": svg_path.name, "digest": _digest(svg_bytes)},
    ]
    if args.baseline is not None:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        delta = ArchitectureDeltaProvider().compare(baseline, graph, delta_id=f"{args.graph_id}-delta")
        delta_bytes = (json.dumps(delta, indent=2, sort_keys=True) + "\n").encode()
        delta_svg_bytes = renderer.render_delta(delta).encode()
        delta_path = args.output / "architecture-delta.json"
        delta_svg_path = args.output / "architecture-delta.svg"
        delta_path.write_bytes(delta_bytes)
        delta_svg_path.write_bytes(delta_svg_bytes)
        artifacts.extend([
            {"kind": "delta", "path": delta_path.name, "digest": _digest(delta_bytes)},
            {"kind": "svg", "path": delta_svg_path.name, "digest": _digest(delta_svg_bytes)},
        ])
    manifest = {
        "schema": "architecture-artifact-manifest.v1",
        "artifact_id": args.graph_id,
        "graph_ref": {"graph_id": graph["graph_id"], "graph_version": graph["graph_version"], "digest": graph["digest"]},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "limitations": graph["limitations"],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    # The manifest does not self-hash; its own file digest would be recursive.
    (args.output / "manifest.json").write_bytes(manifest_bytes)
    print(json.dumps({"output": str(args.output), "artifacts": [item["path"] for item in artifacts] + ["manifest.json"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
