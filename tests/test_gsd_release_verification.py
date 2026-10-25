from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from adapters.radix.capabilities import CapabilitySelectionError, verify_gsd_release_bundle


class GsdReleaseVerificationTests(unittest.TestCase):
    def _write_fixture(self, root: Path, *, content: bytes = b"skill\n") -> Path:
        (root / "SKILL.md").write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        bundle_digest = "sha256:" + hashlib.sha256(
            b"SKILL.md\0" + digest.encode("ascii") + b"\n"
        ).hexdigest()
        manifest = root.parent / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": "gsd-master-release-manifest.v1",
                    "capability_id": "gsd.master",
                    "version": "3.3.4",
                    "bundle_digest": bundle_digest,
                    "files": [{"path": "SKILL.md", "sha256": digest, "bytes": len(content)}],
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_release_manifest_and_bundle_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._write_fixture(root)
            result = verify_gsd_release_bundle(root, manifest_path=manifest)
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["files"], 1)

    def test_modified_release_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._write_fixture(root)
            (root / "SKILL.md").write_bytes(b"tampered\n")
            with self.assertRaisesRegex(CapabilitySelectionError, "digest/size mismatch"):
                verify_gsd_release_bundle(root, manifest_path=manifest)
