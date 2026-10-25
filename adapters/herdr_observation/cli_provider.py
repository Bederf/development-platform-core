"""Read-only provider for the documented Herdr CLI snapshot surface."""

from __future__ import annotations

import json
import os
import subprocess

from .transport import TransportError, negotiate_protocol


class HerdrCliSnapshotProvider:
    """Fetch current Herdr state without exposing any mutation operation."""

    def __init__(self, *, executable: str = "herdr", runner=None):
        self.executable = executable
        self.runner = runner or subprocess.run

    def snapshot(self) -> dict:
        if os.environ.get("HERDR_ENV") != "1":
            raise TransportError("live Herdr access requires HERDR_ENV=1")
        completed = self.runner(
            [self.executable, "api", "snapshot"],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            response = json.loads(completed.stdout)
            snapshot = response["result"]["snapshot"]
            negotiate_protocol(int(snapshot["protocol"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TransportError("malformed Herdr snapshot response") from exc
        return snapshot

    def pane(self, pane_id: str) -> dict:
        for pane in self.snapshot().get("panes", []):
            if pane.get("pane_id") == pane_id:
                return pane
        raise TransportError(f"pane not found in Herdr snapshot: {pane_id}")
