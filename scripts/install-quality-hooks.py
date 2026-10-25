#!/usr/bin/env python3
"""Install/reconcile owned hooks without replacing existing enforcement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

CORE = Path(__file__).resolve().parents[1]
MARKER = "# Development Platform Core managed quality configuration v1\n"
INTEGRATION_MARKER = "# Development Platform Core quality gate integration v1"


def wrapper(scope: str) -> str:
    return (
        "#!/usr/bin/env bash\n" + MARKER + "set -euo pipefail\n"
        'CORE_ROOT="${DEVELOPMENT_PLATFORM_CORE:-}"\n'
        f'if [[ -z "$CORE_ROOT" ]]; then CORE_ROOT={shlex.quote(str(CORE))}; fi\n'
        f'exec bash "$CORE_ROOT/.githooks/review-gate.sh" {scope} "$@"\n'
    )


def preflight(root: Path) -> bool:
    configured = subprocess.run(
        ["git", "-C", str(root), "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
    )
    if configured.returncode not in (0, 1):
        raise ValueError("cannot resolve Git hooks configuration")
    husky_owner = False
    if configured.returncode == 0:
        configured_path = (root / configured.stdout.strip()).resolve()
        if configured_path != root / ".githooks":
            husky_path = (root / ".husky" / "_").resolve()
            hooks = (root / ".husky" / "pre-commit", root / ".husky" / "pre-push")
            husky_owner = configured_path == husky_path and all(
                hook.is_file() and INTEGRATION_MARKER in hook.read_text()
                for hook in hooks
            )
            if not husky_owner:
                raise ValueError(
                    "existing core.hooksPath must be reconciled before initialization"
                )
    if configured.returncode == 1:
        default = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--git-path", "hooks"], text=True
        ).strip()
        for path in (root / default).glob("*"):
            if path.is_file() and not path.name.endswith(".sample"):
                raise ValueError(
                    "existing Git hooks must be reconciled before initialization"
                )
    for name in (
        ".githooks",
        ".development-platform",
        ".agents/skills",
        "docs/development-platform-quality.md",
        "tests/property/README.md",
        "development-platform.yaml",
        ".development-platform/skills.yaml",
        ".development-platform/capabilities.yaml",
    ):
        path = root / name
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"output path escapes project: {name}")
    for path in (root / ".agents/skills").rglob("*"):
        if not path.resolve().is_relative_to(root):
            raise ValueError("existing skill path escapes project")
    for name, scope in [("pre-commit", "staged"), ("pre-push", "push")]:
        path = root / ".githooks" / name
        if path.is_symlink() or (path.exists() and path.read_text() != wrapper(scope)):
            raise ValueError(
                f"existing {name} is not an unchanged Core hook; preserve and reconcile it first"
            )
    for name in (
        ".development-platform/quality.yaml",
        "docs/development-platform-quality.md",
    ):
        path = root / name
        if path.is_symlink() or (
            path.exists() and not path.read_text().startswith(MARKER)
        ):
            raise ValueError(f"existing {name} is consumer-owned; reconcile it first")
    config = root / ".development-platform/quality-hooks.json"
    if config.is_symlink():
        raise ValueError("quality hook configuration must not be a symlink")
    if config.exists():
        settings = json.loads(config.read_text())
        if (
            not isinstance(settings, dict)
            or settings.get("schema") != "development-quality-hooks.v1"
        ):
            raise ValueError("existing quality hook configuration is not Core-owned")
    return husky_owner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument(
        "--ocr-transport", default="direct", choices=["direct"]
    )
    parser.add_argument("--review-command", default="")
    parser.add_argument("--infisical-project-id", default="")
    parser.add_argument("--infisical-env", default="prod")
    parser.add_argument("--infisical-path", default="/omniroute")
    args = parser.parse_args()
    try:
        root = args.project.resolve()
        husky_owner = preflight(root)
        if args.check:
            return 0
        ai = (
            "ocr" in args.capability
            and "ocr=ocr.deterministic@1.0.0" not in args.profile
        )
        config = {
            "schema": "development-quality-hooks.v1",
            "ai_review": ai,
            "transport": args.ocr_transport,
            "infisical_project_id": args.infisical_project_id,
            "infisical_env": args.infisical_env,
            "infisical_path": args.infisical_path,
        }
        if args.review_command:
            config["review_command"] = args.review_command
        for name in (".githooks", ".development-platform", "docs"):
            (root / name).mkdir(parents=True, exist_ok=True)
        for name, scope in [("pre-commit", "staged"), ("pre-push", "push")]:
            path = root / ".githooks" / name
            path.write_text(wrapper(scope))
            path.chmod(0o755)
        (root / ".development-platform/quality-hooks.json").write_text(
            json.dumps(config, indent=2) + "\n"
        )
        quality = (
            MARKER
            + "schema: development-quality.v1\nocr:\n  deterministic_gate: enabled\n"
            f"  ai_review: {'configured-push-only' if ai else 'disabled'}\n  transport: {args.ocr_transport}\n"
            "  provider_verified: false\nbackpass:\n"
            f"  capture: {'opt-in' if 'backpass' in args.capability else 'disabled'}\n"
            "  transmission: disabled\n  signing_key: external-secret-manager\nproperty_testing:\n"
            f"  scaffold: {'present' if 'property-testing' in args.capability else 'disabled'}\n  runner: project-defined\n"
        )
        (root / ".development-platform/quality.yaml").write_text(quality)
        docs = (
            MARKER + "# Development platform quality capabilities\n\n"
            "Commits run deterministic checks on staged content. Pushes check each outgoing ref against its remote base; new refs check the full tip tree. Git failures block the push.\n\n"
            f"External AI review is {'configured for pushes only' if ai else 'disabled by the selected capabilities/profiles'}. "
            "Direct transport is the default. OmniRoute is optional and only used when explicitly selected; direct review needs no OmniRoute or Infisical configuration.\n\n"
            "The Core-owned reviewer uses its installed provider configuration. OPEN_CODE_REVIEW_CMD may name another approved reviewer; it receives immutable changed files in an isolated directory. Provider credentials and live availability are not verified by initialization. Review has a five-minute process deadline. Incomplete results fail; findings are reported, with no implicit severity threshold.\n\n"
            "SKIP_OPEN_CODE_REVIEW=1 is an explicit emergency bypass requiring a recorded operator decision. Deterministic checks still run.\n\n"
            "Backpass capture remains opt-in and transmission disabled pending a session adapter, redaction policy and secret mapping. Property testing supplies a scaffold only; the project must supply its runner and domain properties.\n\n"
            "Reapplying an approved plan updates unchanged Core hooks and their configuration. Existing consumer hooks or edited generated hooks cause a conflict before application.\n"
        )
        (root / "docs/development-platform-quality.md").write_text(docs)
        if not husky_owner:
            subprocess.run(
                ["git", "-C", str(root), "config", "core.hooksPath", ".githooks"],
                check=True,
            )
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"quality initialization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
