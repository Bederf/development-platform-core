from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from adapters.radix import RadixStartupAdapter


class ADR005LauncherConformanceTests(unittest.TestCase):
    """Red-first tests for ADR-005 obligations before launcher implementation."""

    def test_unknown_declaration_field_fails_closed(self) -> None:
        with self.consumer() as (root, declaration):
            declaration.write_text(
                declaration.read_text(encoding="utf-8")
                + "\nplatform_authority: consumer-invented\n",
                encoding="utf-8",
            )
            resolution = self.adapter(declaration).resolve_startup(
                session_id="unknown-field", agent="codex"
            )
            self.assertFalse(resolution.ready)
            self.assertFalse(resolution.execution_allowed)
            self.assertIn("declaration", resolution.blocking_reasons)

    def test_ambiguous_declaration_type_fails_closed(self) -> None:
        with self.consumer() as (root, declaration):
            text = declaration.read_text(encoding="utf-8").replace(
                "  enabled: true\n  provider: code-review-graph",
                "  enabled: 'true'\n  provider: code-review-graph",
            )
            declaration.write_text(text, encoding="utf-8")
            resolution = self.adapter(declaration).resolve_startup(
                session_id="wrong-type", agent="codex"
            )
            self.assertFalse(resolution.ready)
            self.assertFalse(resolution.execution_allowed)
            self.assertIn("declaration", resolution.blocking_reasons)

    def test_parent_escape_is_not_an_authorized_root(self) -> None:
        with self.consumer() as (root, declaration):
            text = declaration.read_text(encoding="utf-8").replace(
                "  knowledge_root: vault", "  knowledge_root: ../"
            )
            declaration.write_text(text, encoding="utf-8")
            resolution = self.adapter(declaration).resolve_startup(
                session_id="parent-escape", agent="codex"
            )
            self.assertFalse(resolution.ready)
            self.assertFalse(resolution.execution_allowed)
            self.assertIn("path_policy", resolution.blocking_reasons)

    def test_external_root_requires_explicit_platform_grant(self) -> None:
        with self.consumer() as (root, declaration):
            with tempfile.TemporaryDirectory() as outside_directory:
                outside = Path(outside_directory)
                text = declaration.read_text(encoding="utf-8").replace(
                    "  knowledge_root: vault", f"  knowledge_root: {outside / 'knowledge'}"
                )
                (outside / "knowledge").mkdir()
                declaration.write_text(text, encoding="utf-8")

                resolution = RadixStartupAdapter(
                    declaration,
                    repository_intelligence=self.adapter(declaration)._repository_intelligence,
                ).resolve_startup(session_id="external-denied", agent="codex")
                self.assertFalse(resolution.ready)
                self.assertIn("path_policy", resolution.blocking_reasons)

                granted = RadixStartupAdapter(
                    declaration,
                    repository_intelligence=self.adapter(declaration)._repository_intelligence,
                    allowed_external_roots=[outside],
                ).resolve_startup(session_id="external-granted", agent="codex")
                self.assertTrue(granted.ready)
                self.assertEqual(granted.provenance["path_kinds"]["knowledge_root"], "external_permitted")

    def test_resolution_provenance_is_reconstructable_and_deterministic(self) -> None:
        with self.consumer() as (root, declaration):
            first = self.adapter(declaration).resolve_startup(
                session_id="provenance-test", agent="codex"
            )
            second = self.adapter(declaration).resolve_startup(
                session_id="provenance-test", agent="codex"
            )
            self.assertEqual(first.provenance, second.provenance)
            self.assertEqual(first.provenance["objective"]["source"], "task_authority")
            self.assertEqual(first.provenance["path_kinds"]["repository_root"], "canonical")
            self.assertEqual(first.provenance["blocking_reasons"], [])

    def test_consumer_cannot_invent_objective_over_task_authority(self) -> None:
        with self.consumer() as (root, declaration):
            resolution = self.adapter(declaration).resolve_startup(
                session_id="objective-injection",
                agent="codex",
                current_objective="consumer-invented authority",
            )
            self.assertFalse(resolution.ready)
            self.assertFalse(resolution.execution_allowed)
            self.assertIn("objective", resolution.blocking_reasons)

    def test_consumer_invented_task_authority_is_blocked(self) -> None:
        with self.consumer() as (root, declaration):
            text = declaration.read_text(encoding="utf-8").replace(
                "  task_authority: TODO.md", "  task_authority: ../consumer-authority.md"
            )
            declaration.write_text(text, encoding="utf-8")
            resolution = self.adapter(declaration).resolve_startup(
                session_id="authority-injection", agent="codex"
            )
            self.assertFalse(resolution.ready)
            self.assertFalse(resolution.execution_allowed)
            self.assertIn("path_policy", resolution.blocking_reasons)

    def test_symlink_escape_is_not_an_authorized_root(self) -> None:
        with self.consumer() as (root, declaration):
            with tempfile.TemporaryDirectory() as outside_directory:
                outside = Path(outside_directory)
                (outside / "planning").mkdir()
                (root / "vault").rename(root / "vault-original")
                (root / "vault").symlink_to(outside, target_is_directory=True)
                resolution = self.adapter(declaration).resolve_startup(
                    session_id="symlink-escape", agent="codex"
                )
                self.assertFalse(resolution.ready)
                self.assertFalse(resolution.execution_allowed)
                self.assertIn("path_policy", resolution.blocking_reasons)

    @staticmethod
    def adapter(declaration: Path) -> RadixStartupAdapter:
        return RadixStartupAdapter(declaration, repository_intelligence=lambda root, objective: {
            "schema": "repository-intelligence.v1",
            "status": "CURRENT",
            "provider": "test",
            "generated_at": "2026-08-17T00:00:00+00:00",
            "indexed_revision": "test",
            "trusted": True,
            "relevant_files": [],
            "relevant_symbols": [],
            "notes": [],
            "freshness_evidence": [],
        })

    @staticmethod
    def consumer():
        class Consumer:
            def __enter__(self):
                self.temp = tempfile.TemporaryDirectory()
                root = Path(self.temp.name)
                (root / "vault").mkdir()
                (root / "00-GSD-Phases").mkdir()
                (root / "TODO.md").write_text(
                    "- [ ] platform-authorized objective\n", encoding="utf-8"
                )
                declaration = root / "development-platform.yaml"
                declaration.write_text(
                    "schema: development-platform.v1\n"
                    "project:\n"
                    "  id: hostile-test-consumer\n"
                    "  root: .\n"
                    "  knowledge_root: vault\n"
                    "  planning_root: 00-GSD-Phases\n"
                    "repository_intelligence:\n"
                    "  enabled: true\n"
                    "  provider: code-review-graph\n"
                    "  degraded_mode: block\n"
                    "agents:\n"
                    "  codex: true\n"
                    "gsd:\n"
                    "  enabled: true\n"
                    "  task_authority: TODO.md\n",
                    encoding="utf-8",
                )
                return root, declaration

            def __exit__(self, exc_type, exc, traceback):
                self.temp.cleanup()

        return Consumer()


if __name__ == "__main__":
    unittest.main()
