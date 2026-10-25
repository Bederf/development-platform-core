from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from adapters.radix.capabilities import CapabilitySelectionError, resolve_capabilities


def write_manifest(root: Path, body: str) -> None:
    path = root / ".development-platform"
    path.mkdir()
    (path / "capabilities.yaml").write_text(body, encoding="utf-8")


class RadixCapabilityResolutionTests(unittest.TestCase):
    def test_missing_manifest_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            result = resolve_capabilities(Path(directory), "example")
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["selections"], {})

    def test_enabled_selection_resolves_against_core_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  ocr:
    enabled: true
    implementation: core.ocr-gate
    version: 1.0.0
""",
            )
            result = resolve_capabilities(root, "example")
            self.assertEqual(result["status"], "resolved")
            self.assertTrue(result["selections"]["ocr"]["enabled"])

    def test_enabled_governed_engineering_loop_resolves_against_core_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  governed-engineering-loop:
    enabled: true
    implementation: core.governed-engineering-loop
    version: 1.0.0
""",
            )
            result = resolve_capabilities(root, "example")
            selection = result["selections"]["governed-engineering-loop"]
            self.assertEqual(selection["adapter"], "core-skill-projection")
            self.assertEqual(selection["readiness"], "ready")

    def test_gsd_workflow_provider_selection_is_explicit_and_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  gsd:
    enabled: false
    implementation: gsd.master
    version: 3.3.0
    configuration:
      workflow_providers:
        SPECIFICATION:
          provider: spec-kit
          version: 1.0.4
""",
            )
            selection = resolve_capabilities(root, "example")["selections"]["gsd"]
            configured = selection["configuration"]["workflow_providers"]["SPECIFICATION"]
            self.assertEqual(configured["provider"], "spec-kit")
            self.assertEqual(configured["readiness"], "ready")

    def test_promoted_gsd_verifies_installed_bundle_without_explicit_source(self):
        """The promoted version is digest-verified against the declared implementation root."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  gsd:
    enabled: true
    implementation: gsd.master
    version: 3.3.4
""",
            )
            selection = resolve_capabilities(root, "example")["selections"]["gsd"]
            verification = selection["configuration"]["release_verification"]
            self.assertEqual(verification["status"], "verified")
            self.assertEqual(verification["version"], "3.3.4")
            self.assertEqual(
                verification["bundle_digest"],
                "sha256:5fc09294da0c15eeb9f2f4a45ec1393f2b79131e94b8cf8af361c30c12894f7c",
            )

    def test_explicit_source_root_override_fails_closed_on_mismatch(self):
        """An explicit source_root still overrides, and a non-matching bundle fails closed."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty_target = root / "not-the-bundle"
            empty_target.mkdir()
            write_manifest(
                root,
                f"""schema: development-capability-selection.v1
project_id: example
capabilities:
  gsd:
    enabled: true
    implementation: gsd.master
    version: 3.3.4
    configuration:
      source_root: {empty_target}
""",
            )
            with self.assertRaisesRegex(CapabilitySelectionError, "file set mismatch"):
                resolve_capabilities(root, "example")

    def test_unsupported_gsd_workflow_provider_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  gsd:
    enabled: true
    implementation: gsd.master
    version: 3.3.0
    configuration:
      workflow_providers:
        PLAN:
          provider: unknown
          version: 1.0.0
""",
            )
            with self.assertRaisesRegex(CapabilitySelectionError, "unsupported GSD workflow provider"):
                resolve_capabilities(root, "example")

    def test_custom_manifest_path_is_resolved_without_falling_back_to_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom = root / "config" / "capabilities.yaml"
            custom.parent.mkdir()
            custom.write_text(
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  governed-engineering-loop:
    enabled: true
    implementation: core.governed-engineering-loop
    version: 1.0.0
""",
                encoding="utf-8",
            )
            result = resolve_capabilities(root, "example", "config/capabilities.yaml")
            self.assertEqual(result["status"], "resolved")
            self.assertIn("governed-engineering-loop", result["selections"])

    def test_enabled_selection_with_wrong_implementation_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  gsd:
    enabled: true
    implementation: project-defined
    version: 3.3.0
""",
            )
            with self.assertRaisesRegex(CapabilitySelectionError, "does not match Core registry"):
                resolve_capabilities(root, "example")

    def test_enabled_selection_resolves_a_matching_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  ocr:
    enabled: true
    implementation: core.ocr-gate
    version: 1.0.0
    profiles:
      - id: ocr.deterministic
        version: 1.0.0
""",
            )
            result = resolve_capabilities(root, "example")
            self.assertEqual(result["selections"]["ocr"]["profiles"], [{"id": "ocr.deterministic", "version": "1.0.0"}])

    def test_profile_with_wrong_base_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  property-testing:
    enabled: true
    implementation: project-defined
    version: 1.0.0
    profiles:
      - id: ocr.deterministic
        version: 1.0.0
""",
            )
            with self.assertRaisesRegex(CapabilitySelectionError, "base does not match"):
                resolve_capabilities(root, "example")

    def test_profile_on_disabled_capability_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(
                root,
                """schema: development-capability-selection.v1
project_id: example
capabilities:
  ocr:
    enabled: false
    implementation: core.ocr-gate
    version: 1.0.0
    profiles:
      - id: ocr.deterministic
        version: 1.0.0
""",
            )
            with self.assertRaisesRegex(CapabilitySelectionError, "disabled capability"):
                resolve_capabilities(root, "example")


if __name__ == "__main__":
    unittest.main()
