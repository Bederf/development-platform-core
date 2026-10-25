from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from adapters.radix.cli import main
from adapters.radix.governance import governance_digest, load_governance_record
from adapters.radix.startup import RadixStartupAdapter, StartupConfigurationError


def governance_record(root: Path, *, status: str = "confirmed") -> dict:
    record = {
        "schema": "project-governance.v1",
        "context_id": "governance.fixture.001",
        "project_id": "fixture-project",
        "repository_root": str(root.resolve()),
        "status": status,
        "owner": {
            "identity": "owner.fixture",
            "role": "accountable project owner",
            "confirmed_by": "owner.fixture",
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        },
        "mandate": {
            "purpose": "Build the governed fixture",
            "scope": ["architecture discovery"],
            "exclusions": ["production deployment"],
        },
        "authority": {
            key: {
                "authority_ref": f"fixture.{key}",
                "decisions": ["review"],
                "scope": ["project"],
                "prohibited": ["production activation"],
            }
            for key in ("project_owner", "architecture", "engineering", "release", "operations")
        },
        "review": {"independent_required": True, "authority_ref": "fixture.independent-review"},
        "approval_policy": {
            "lifecycle": ["generated", "reviewed", "approved", "operational"],
            "separate_decisions": ["implementation", "release", "production"],
        },
        "delegations": [],
        "provenance": {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "record_digest": "sha256:" + "0" * 64,
            "source": "fixture-owner-confirmation",
            "supersedes": None,
        },
    }
    record["provenance"]["record_digest"] = governance_digest(record)
    return record


class ProjectGovernanceTests(unittest.TestCase):
    def test_governance_record_is_content_addressed_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = governance_record(root)
            path = root / "governance.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            loaded = load_governance_record(path, project_id="fixture-project", repository_root=root)
            self.assertEqual(loaded["provenance"]["record_digest"], governance_digest(record))

    def test_startup_propagates_governance_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = governance_record(root)
            (root / ".development-platform").mkdir()
            (root / ".development-platform/governance.json").write_text(json.dumps(record), encoding="utf-8")
            (root / "TODO.md").write_text("- [ ] governed task\n", encoding="utf-8")
            (root / "development-platform.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema": "development-platform.v1",
                        "project": {"id": "fixture-project", "root": "."},
                        "governance": {
                            "required": True,
                            "context_path": ".development-platform/governance.json",
                            "context_digest": record["provenance"]["record_digest"],
                        },
                        "repository_intelligence": {"enabled": False},
                        "agents": {"codex": True},
                        "gsd": {"enabled": True, "task_authority": "TODO.md"},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            context = RadixStartupAdapter(root / "development-platform.yaml").build_context(session_id="fixture")
            self.assertEqual(context["governance"]["status"], "confirmed")
            self.assertEqual(context["governance"]["owner"]["identity"], "owner.fixture")

    def test_startup_rejects_mismatched_governance_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = governance_record(root)
            (root / "governance.json").write_text(json.dumps(record), encoding="utf-8")
            declaration = root / "development-platform.yaml"
            declaration.write_text(
                yaml.safe_dump(
                    {
                        "schema": "development-platform.v1",
                        "project": {"id": "fixture-project", "root": "."},
                        "governance": {"required": True, "context_path": "governance.json", "context_digest": "sha256:" + "f" * 64},
                        "repository_intelligence": {"enabled": False},
                        "agents": {"codex": True},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(StartupConfigurationError):
                RadixStartupAdapter(declaration).build_context(session_id="fixture")

    def test_governed_init_requires_and_installs_confirmed_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            record = governance_record(root)
            source = root / "owner-governance.json"
            source.write_text(json.dumps(record), encoding="utf-8")
            plan_path = root / "plan.json"
            output = io.StringIO()
            self.assertEqual(
                main(
                    [
                        "init", "--project", str(root), "--project-id", "fixture-project",
                        "--capability", "security-audit", "--governed",
                        "--governance-record", str(source), "--output", str(plan_path),
                    ],
                    stdout=output,
                ),
                0,
                output.getvalue(),
            )
            self.assertEqual(main(["init", "--project", str(root), "--apply", str(plan_path), "--approve"], stdout=io.StringIO()), 0)
            declaration = yaml.safe_load((root / "development-platform.yaml").read_text(encoding="utf-8"))
            self.assertTrue(declaration["governance"]["required"])
            self.assertEqual(declaration["governance"]["context_digest"], governance_digest(record))
            self.assertTrue((root / ".development-platform/governance.json").is_file())


if __name__ == "__main__":
    unittest.main()
