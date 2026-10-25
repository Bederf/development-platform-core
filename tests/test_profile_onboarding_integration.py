"""End-to-end fake-project qualification for capability profiles."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver

from adapters.radix.startup import RadixStartupAdapter
from adapters.radix.capabilities import CapabilitySelectionError, resolve_capabilities


ROOT = Path(__file__).resolve().parents[1]


class ProfileOnboardingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema_path = ROOT / "contracts/agent-startup-context.v1.schema.json"
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema, resolver=RefResolver(self.schema_path.as_uri(), schema))

    def project(self) -> Path:
        directory = Path(tempfile.mkdtemp())
        (directory / "agents").mkdir()
        subprocess.run(["git", "init", "-q", str(directory)], check=True)
        (directory / "development-platform.yaml").write_text(
            """schema: development-platform.v1
project:
  id: fixture-profile-project
  root: .
  knowledge_root: ./
  planning_root: ./planning/
repository_intelligence:
  enabled: false
  provider: none
agents:
  codex: true
gsd:
  enabled: false
""",
            encoding="utf-8",
        )
        return directory

    def test_initializer_and_radix_preserve_explicit_profile_without_activation(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            project = self.project()
            subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/init-development-quality.sh"),
                    "--project",
                    str(project),
                    "--project-id",
                    "fixture-profile-project",
                    "--capability",
                    "ocr",
                    "--profile",
                    "ocr=ocr.deterministic@1.0.0",
                ],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                text=True,
            )
            context = RadixStartupAdapter(project / "development-platform.yaml").build_context(
                session_id="profile-integration", current_objective="qualification"
            )
            self.validator.validate(context)
            selection = context["capabilities"]["selections"]["ocr"]
            self.assertEqual(selection["profiles"], [{"id": "ocr.deterministic", "version": "1.0.0"}])
            self.assertNotIn("active", selection)
            self.assertEqual(context["session_brief"]["status"], "unavailable")
            hook = (project / ".githooks/pre-commit").read_text(encoding="utf-8")
            self.assertIn("review-gate.sh\" staged", hook)
            self.assertIn("DEVELOPMENT_PLATFORM_CORE", hook)
            quality = (project / ".development-platform/quality.yaml").read_text(encoding="utf-8")
            self.assertIn("ai_review: disabled", quality)

    def test_unknown_profile_fails_closed_after_initializer_scaffolding(self) -> None:
        project = self.project()
        subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/init-development-quality.sh"),
                "--project",
                str(project),
                "--project-id",
                "fixture-profile-project",
                "--capability",
                "ocr",
                "--profile",
                "ocr=unknown.profile@1.0.0",
            ],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            text=True,
        )
        with self.assertRaisesRegex(CapabilitySelectionError, "unsupported capability profile"):
            resolve_capabilities(project, "fixture-profile-project")

    def test_initializer_disables_ai_review_when_ocr_is_not_selected(self) -> None:
        project = self.project()
        subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/init-development-quality.sh"),
                "--project",
                str(project),
                "--project-id",
                "fixture-profile-project",
            ],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            text=True,
        )
        hook = (project / ".githooks/pre-commit").read_text(encoding="utf-8")
        settings = json.loads((project / ".development-platform/quality-hooks.json").read_text())
        self.assertFalse(settings["ai_review"])
        quality = (project / ".development-platform/quality.yaml").read_text(encoding="utf-8")
        self.assertIn("ai_review: disabled", quality)

    def test_initializer_can_generate_infisical_omniroute_launcher(self) -> None:
        project = self.project()
        subprocess.run(
            [
                "bash", str(ROOT / "scripts/init-development-quality.sh"),
                "--project", str(project), "--project-id", "fixture-profile-project",
                "--capability", "ocr", "--ocr-transport", "omniroute",
                "--infisical-project-id", "core-project-id",
            ],
            check=True, cwd=ROOT, stdout=subprocess.PIPE, text=True,
        )
        hook = (project / ".githooks/pre-commit").read_text(encoding="utf-8")
        self.assertNotIn("infisical", hook)
        settings = json.loads((project / ".development-platform/quality-hooks.json").read_text())
        self.assertEqual(settings["transport"], "omniroute")
        self.assertEqual(settings["infisical_project_id"], "core-project-id")
        self.assertIn('"$CORE_ROOT/.githooks/review-gate.sh" staged', hook)
        quality = (project / ".development-platform/quality.yaml").read_text(encoding="utf-8")
        self.assertIn("transport: omniroute", quality)

    def test_mismatched_profile_fails_closed(self) -> None:
        project = self.project()
        manifest_dir = project / ".development-platform"
        manifest_dir.mkdir()
        (manifest_dir / "capabilities.yaml").write_text(
            """schema: development-capability-selection.v1
project_id: fixture-profile-project
capabilities:
  property-testing:
    enabled: true
    implementation: project-defined
    version: 1.0.0
    profiles:
      - id: ocr.deterministic
        version: 1.0.0
""",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilitySelectionError, "base does not match"):
            resolve_capabilities(project, "fixture-profile-project")


if __name__ == "__main__":
    unittest.main()
