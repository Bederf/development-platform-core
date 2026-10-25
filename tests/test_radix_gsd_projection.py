from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from adapters.radix.cli import main as radix_main
from adapters.radix.gsd_projection import (
    GsdProjectionError,
    verify_codex_projection,
    write_launch_attestation,
)


def _manifest(root: Path, *, version: str = "3.3.4") -> Path:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            content = path.read_bytes()
            entries.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
    canonical = b"".join(
        item["path"].encode() + b"\0" + item["sha256"].encode() + b"\n" for item in entries
    )
    payload = {
        "schema": "gsd-master-release-manifest.v1",
        "capability_id": "gsd.master",
        "version": version,
        "bundle_digest": "sha256:" + hashlib.sha256(canonical).hexdigest(),
        "files": entries,
    }
    manifest = root.parent / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest


def _bundle(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: gsd-master\nalias: gsd:master\nversion: 3.3.4\n---\n# GSD\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# bundle\n", encoding="utf-8")


class RadixGsdProjectionTests(unittest.TestCase):
    def capability(self, source: Path, manifest: Path) -> dict[str, object]:
        return {
            "enabled": True,
            "implementation": "gsd.master",
            "version": "3.3.4",
            "configuration": {"source_root": str(source), "release_manifest": str(manifest)},
        }

    def test_verifies_one_codex_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            _bundle(source)
            manifest = _manifest(source)
            home = root / "codex-home"
            projection = home / "skills" / "gsd-master"
            for file in source.iterdir():
                projection.parent.mkdir(parents=True, exist_ok=True)
                projection.mkdir(exist_ok=True)
                (projection / file.name).write_bytes(file.read_bytes())
            result = verify_codex_projection(
                project_root=root / "project",
                capability=self.capability(source, manifest),
                agent_args=[],
                environ={"CODEX_HOME": str(home)},
            )
            self.assertEqual(result["result"], "verified")
            self.assertEqual(result["actual_consumption"], "UNVERIFIED")
            self.assertEqual(result["projection_path"], str(projection.resolve()))

    def test_duplicate_projection_candidates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            _bundle(source)
            manifest = _manifest(source)
            home = root / "codex-home"
            for name in ("gsd-master", "gsd-master-3.3.4"):
                target = home / "skills" / name
                target.mkdir(parents=True)
                for file in source.iterdir():
                    (target / file.name).write_bytes(file.read_bytes())
            with self.assertRaisesRegex(GsdProjectionError, "ambiguous"):
                verify_codex_projection(
                    project_root=root / "project",
                    capability=self.capability(source, manifest),
                    agent_args=[],
                    environ={"CODEX_HOME": str(home)},
                )

    def test_explicit_projection_selection_resolves_multiple_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            _bundle(source)
            manifest = _manifest(source)
            home = root / "codex-home"
            projections = []
            for name in ("gsd-master", "gsd-master-3.3.4"):
                target = home / "skills" / name
                target.mkdir(parents=True)
                for file in source.iterdir():
                    (target / file.name).write_bytes(file.read_bytes())
                projections.append(target)
            capability = self.capability(source, manifest)
            capability["configuration"]["projection_path"] = str(projections[1])
            result = verify_codex_projection(
                project_root=root / "project",
                capability=capability,
                agent_args=[],
                environ={"CODEX_HOME": str(home)},
            )
            self.assertEqual(result["result"], "verified")
            self.assertEqual(result["projection_path"], str(projections[1].resolve()))

    def test_configured_projection_must_be_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            _bundle(source)
            manifest = _manifest(source)
            capability = self.capability(source, manifest)
            capability["configuration"]["projection_path"] = str(root / "outside")
            with self.assertRaisesRegex(GsdProjectionError, "was not discovered"):
                verify_codex_projection(
                    project_root=root / "project",
                    capability=capability,
                    agent_args=[],
                    environ={"CODEX_HOME": str(root / "codex-home")},
                )

    def test_unsafe_projection_files_fail_closed(self) -> None:
        for kind in ("symlink", "hardlink", "special"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                _bundle(source)
                manifest = _manifest(source)
                projection = root / "codex-home" / "skills" / "gsd-master"
                projection.mkdir(parents=True)
                for file in source.iterdir():
                    (projection / file.name).write_bytes(file.read_bytes())
                if kind == "symlink":
                    (projection / "README.md").unlink()
                    (projection / "README.md").symlink_to(source / "README.md")
                elif kind == "hardlink":
                    (projection / "README.md").unlink()
                    (projection / "README.md").hardlink_to(projection / "SKILL.md")
                else:
                    (projection / "README.md").unlink()
                    (projection / "README.md").touch()
                    import os

                    os.mkfifo(projection / "pipe")
                with self.assertRaisesRegex(GsdProjectionError, "symlink|hard-linked|special|digest"):
                    verify_codex_projection(
                        project_root=root / "project",
                        capability=self.capability(source, manifest),
                        agent_args=[],
                        environ={"CODEX_HOME": str(root / "codex-home")},
                    )

    def test_enabled_gsd_ambiguity_blocks_radix_executor_and_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vault").mkdir()
            (root / "phases").mkdir()
            (root / "TODO.md").write_text("- [ ] verify projection\n", encoding="utf-8")
            source = root / "source"
            _bundle(source)
            manifest = _manifest(source)
            home = root / "codex-home"
            for name in ("gsd-master", "gsd-master-3.3.4"):
                target = home / "skills" / name
                target.mkdir(parents=True)
                for file in source.iterdir():
                    (target / file.name).write_bytes(file.read_bytes())
            (root / "development-platform.yaml").write_text(
                "schema: development-platform.v1\n"
                "project:\n  id: projection-test\n  root: .\n  knowledge_root: vault\n  planning_root: phases\n"
                "repository_intelligence:\n  enabled: false\n  provider: none\n  degraded_mode: startup-without-trusted-context\n"
                "agents:\n  codex: true\n"
                "gsd:\n  enabled: true\n  task_authority: TODO.md\n"
                "capabilities_manifest: .development-platform/capabilities.yaml\n",
                encoding="utf-8",
            )
            capabilities = root / ".development-platform"
            capabilities.mkdir()
            (capabilities / "capabilities.yaml").write_text(
                "schema: development-capability-selection.v1\n"
                "project_id: projection-test\ncapabilities:\n"
                "  gsd:\n    enabled: true\n    implementation: gsd.master\n    version: 3.3.4\n"
                f"    configuration:\n      source_root: {source}\n      release_manifest: {manifest}\n",
                encoding="utf-8",
            )
            calls: list[object] = []
            errors = tempfile.TemporaryFile(mode="w+")
            try:
                result = radix_main(
                    ["--project", str(root), "--codex"],
                    environ={"PATH": "/safe/bin", "CODEX_HOME": str(home)},
                    which=lambda name, path=None: "/safe/bin/codex",
                    executor=lambda *args: calls.append(args),
                    chdir=lambda path: None,
                    stderr=errors,
                )
            finally:
                errors.seek(0)
                failure = errors.read()
                errors.close()
            self.assertEqual(result, 2)
            self.assertEqual(calls, [])
            self.assertIn("RADIX_EXECUTION_ALLOWED=false", failure)
            self.assertIn("ambiguous", failure)
            self.assertFalse((root / ".development-platform" / "attestations").exists())

    def test_discovery_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(GsdProjectionError, "discovery-affecting"):
            from adapters.radix.gsd_projection import reject_discovery_overrides

            reject_discovery_overrides(["--add-dir", "/tmp/other"])

    def test_attestation_is_atomic_and_non_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_launch_attestation(
                project_root=root,
                project_id="example",
                session_id="session-1",
                projection={"result": "verified", "actual_consumption": "UNVERIFIED"},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(payload["authoritative"])
            self.assertEqual(payload["actual_consumption"], "UNVERIFIED")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
