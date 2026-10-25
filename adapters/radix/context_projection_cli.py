"""Workspace-bound CLI for bounded provider startup projections."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .context_projection import ContextProjectionError, StartupContextProjector
from .workspace import WorkspaceDiscoveryError, WorkspaceResolver


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radix-context")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, required=True, help="Projection input JSON")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--format", choices=("json", "prompt"), default="prompt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        binding = WorkspaceResolver().discover(args.project)
        payload: Any = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ContextProjectionError("projection input must be a JSON object")
        declared_project = payload.get("project_id")
        if declared_project is not None and declared_project != binding.project_id:
            raise ContextProjectionError("projection input belongs to another project")
        projector = StartupContextProjector(max_tokens=args.max_tokens)
        projection = projector.project(
            project_id=binding.project_id,
            objective=payload.get("objective"),
            tasks=payload.get("tasks", []),
            brief=payload.get("brief", {"status": "unavailable", "path": None, "text": None}),
            sections=payload.get("sections", []),
            source_documents=payload.get("source_documents", []),
            working_state=payload.get("working_state"),
        )
    except (OSError, json.JSONDecodeError, WorkspaceDiscoveryError, ContextProjectionError) as exc:
        print(f"RADIX_READY=false\nRADIX_EXECUTION_ALLOWED=false\n{exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(projection, indent=2, sort_keys=True))
    else:
        print(projector.render_prompt(projection), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
