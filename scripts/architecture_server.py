#!/usr/bin/env python3
"""Serve derived architecture artifacts on localhost for headless environments."""

from __future__ import annotations

import argparse
import html
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def build_index(root: Path) -> str:
    links = []
    for name, label in (
        ("architecture.svg", "Architecture graph"),
        ("architecture-delta.svg", "Architecture delta"),
        ("architecture-graph.json", "Graph JSON"),
        ("architecture-delta.json", "Delta JSON"),
        ("manifest.json", "Artifact manifest"),
    ):
        if (root / name).is_file():
            links.append(f'<li><a href="/{html.escape(name)}">{html.escape(label)}</a></li>')
    items = "\n".join(links) or "<li>No generated artifacts found.</li>"
    preview = '<img src="/architecture.svg" alt="Architecture graph">' if (root / "architecture.svg").is_file() else ""
    delta = '<img src="/architecture-delta.svg" alt="Architecture delta">' if (root / "architecture-delta.svg").is_file() else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Architecture artifacts</title>
<style>body{{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#172033}}img{{max-width:100%;height:auto;border:1px solid #cbd5e1;margin:1rem 0 2rem}}li{{margin:.5rem 0}}</style>
</head><body><h1>Architecture artifacts</h1><p>Local, derived, read-only presentation surface.</p><ul>{items}</ul>{preview}{delta}</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"artifact root does not exist: {root}")

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("", "/"):
                body = build_index(root).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = ThreadingHTTPServer((args.host, args.port), partial(Handler, directory=str(root)))
    print(f"Architecture viewer: http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
