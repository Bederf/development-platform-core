from pathlib import Path
import tempfile
import unittest

from adapters.radix.capabilities import resolve_capabilities


class SecurityAuditCapabilitySelectionTests(unittest.TestCase):
    def test_security_audit_is_selectable_without_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / ".development-platform" / "capabilities.yaml"
            manifest.parent.mkdir()
            manifest.write_text(
                """schema: development-capability-selection.v1
project_id: example
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

            result = resolve_capabilities(root, "example")

            selection = result["selections"]["security-audit"]
            self.assertTrue(selection["enabled"])
            self.assertEqual(selection["implementation"], "core.security-audit-build")
            self.assertEqual(selection["version"], "1.0.2")
            self.assertEqual(selection["adapter"], "explicit-build-release-command")
            self.assertEqual(selection["configuration"]["pre_commit"], "disabled")


if __name__ == "__main__":
    unittest.main()
