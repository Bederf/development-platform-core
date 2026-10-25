"""Read-only discovery for an optional Spec Kit provider installation."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
import shutil
from typing import Any


def discover_spec_kit(
    *,
    executable: str = "specify",
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str | None]:
    """Discover Spec Kit without installing, initializing, or changing a project."""

    path = which(executable)
    if path is None:
        return {
            "provider": "spec-kit",
            "status": "unavailable",
            "executable": None,
            "version": None,
            "reason": "specify executable is not installed or not on PATH",
        }
    try:
        result = runner([path, "--version"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "provider": "spec-kit",
            "status": "unavailable",
            "executable": path,
            "version": None,
            "reason": f"specify version probe failed: {type(exc).__name__}",
        }
    output = (result.stdout or result.stderr or "").strip().splitlines()
    version = output[0][:128] if output else None
    if result.returncode != 0:
        return {
            "provider": "spec-kit",
            "status": "unavailable",
            "executable": path,
            "version": version,
            "reason": "specify version probe returned a non-zero status",
        }
    return {
        "provider": "spec-kit",
        "status": "available",
        "executable": path,
        "version": version,
        "reason": None,
    }
