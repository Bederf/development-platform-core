from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "development_platform_build_assurance", ROOT / "scripts/development-platform-build-assurance.py"
)
assert SPEC and SPEC.loader
assurance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assurance)


class BuildAssuranceTests(unittest.TestCase):
    def project(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / ".development-platform").mkdir()
        (root / ".development-platform/capabilities.yaml").write_text(
            """schema: development-capability-selection.v1
project_id: fixture-project
capabilities:
  security-audit:
    enabled: true
    implementation: core.security-audit-build
    version: 1.0.2
    configuration:
      execution: explicit-build-release
      pre_commit: disabled
      production: disabled
""",
            encoding="utf-8",
        )
        return root

    def test_delegates_only_after_resolving_baseline(self) -> None:
        project = self.project()
        with patch.object(assurance.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(
                assurance.main(
                    [
                        "--project", str(project),
                        "--audit-package", str(project / "audit"),
                        "--cloudflare-source", str(project / "source"),
                    ]
                ),
                0,
            )
        run.assert_called_once_with(
            [
                str(ROOT / "bin/security-audit-build"),
                "--package", str(project / "audit"),
                "--cloudflare-source", str(project / "source"),
            ],
            cwd=project,
            check=False,
        )

    def test_missing_baseline_fails_before_delegation(self) -> None:
        project = self.project()
        (project / ".development-platform/capabilities.yaml").unlink()
        with patch.object(assurance.subprocess, "run") as run:
            self.assertEqual(
                assurance.main(
                    [
                        "--project", str(project),
                        "--audit-package", str(project / "audit"),
                        "--cloudflare-source", str(project / "source"),
                    ]
                ),
                1,
            )
        run.assert_not_called()

    def test_boundary_configuration_is_required(self) -> None:
        project = self.project()
        manifest = project / ".development-platform/capabilities.yaml"
        payload = manifest.read_text(encoding="utf-8").replace("pre_commit: disabled", "pre_commit: enabled")
        manifest.write_text(payload, encoding="utf-8")
        with patch.object(assurance.subprocess, "run") as run:
            self.assertEqual(
                assurance.main(
                    [
                        "--project", str(project),
                        "--audit-package", str(project / "audit"),
                        "--cloudflare-source", str(project / "source"),
                    ]
                ),
                1,
            )
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
