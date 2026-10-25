"""Dormant Humanizer v0.5 project scaffold."""

from pathlib import Path
import yaml


class HumanizerDisabled(PermissionError):
    """Raised whenever the project Humanizer is not explicitly enabled."""


def require_enabled(project_root: Path) -> dict:
    policy_path = project_root / "config" / "humanizer" / "policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    humanizer = policy.get("humanizer", {}) if isinstance(policy, dict) else {}
    if humanizer.get("enabled") is not True:
        raise HumanizerDisabled("Humanizer is scaffolded but not enabled")
    if humanizer.get("qualification_status") != "approved":
        raise HumanizerDisabled("Humanizer qualification is not approved")
    return policy


def humanize(*_args, **_kwargs):
    raise HumanizerDisabled(
        "Project-local Humanizer implementation is not installed or qualified"
    )
