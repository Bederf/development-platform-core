"""Read-only command surface for deterministic Radix workspace discovery."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .workspace import WorkspaceDiscoveryError, WorkspaceResolver


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radix-workspace",
        description="Resolve the authoritative Radix project for an invocation directory.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Invocation directory; defaults to the current working directory.",
    )
    parser.add_argument(
        "--expect-project",
        help="Fail closed unless the resolved declaration has this project ID.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the binding as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        binding = WorkspaceResolver().discover(
            args.project,
            expected_project_id=args.expect_project,
        )
    except WorkspaceDiscoveryError as exc:
        print(f"RADIX_READY=false\nRADIX_EXECUTION_ALLOWED=false\n{exc}", file=sys.stderr)
        return 2

    payload = binding.to_dict()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"project_id: {payload['project_id']}")
        print(f"repository_root: {payload['repository_root']}")
        print(f"declaration_path: {payload['declaration_path']}")
        print(f"workspace_id: {payload['workspace_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
