from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from adapters.radix.startup import RadixStartupAdapter, StartupResolution


class RadixReadinessTests(unittest.TestCase):
    def test_independent_non_bms_consumer_uses_real_startup_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vault").mkdir()
            (root / "00-GSD-Phases").mkdir()
            (root / "TODO.md").write_text(
                "# Independent consumer tasks\n"
                "- [ ] Validate a consumer-neutral startup\n",
                encoding="utf-8",
            )
            declaration = root / "development-platform.yaml"
            declaration.write_text(
                "schema: development-platform.v1\n"
                "project:\n"
                "  id: independent-consumer\n"
                "  root: .\n"
                "  knowledge_root: vault\n"
                "  planning_root: 00-GSD-Phases\n"
                "repository_intelligence:\n"
                "  enabled: true\n"
                "  provider: code-review-graph\n"
                "  degraded_mode: startup-without-trusted-context\n"
                "agents:\n"
                "  codex: true\n"
                "gsd:\n"
                "  enabled: true\n"
                "  task_authority: TODO.md\n"
                "session_brief:\n"
                "  enabled: false\n"
                "runtime_history:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )

            resolution = RadixStartupAdapter(declaration).resolve_startup(
                session_id="independent-consumer", agent="codex"
            )

            self.assertTrue(resolution.ready)
            self.assertTrue(resolution.execution_allowed)
            self.assertEqual(resolution.blocking_reasons, ())
            assert resolution.context is not None
            self.assertEqual(resolution.context["project_id"], "independent-consumer")
            self.assertEqual(resolution.context["current_objective"], "Validate a consumer-neutral startup")
            self.assertEqual(resolution.context["repository_intelligence"]["status"], "UNAVAILABLE")

    def test_development_platform_core_real_declaration_is_consumer_neutral(self) -> None:
        root = Path(__file__).resolve().parents[1]
        declaration = root / "development-platform.yaml"
        self.assertTrue(declaration.is_file())

        resolution = self.adapter(declaration, "CURRENT").resolve_startup(
            session_id="platform-core-test", agent="codex"
        )

        self.assertTrue(resolution.ready)
        self.assertTrue(resolution.execution_allowed)
        self.assertEqual(resolution.blocking_reasons, ())
        self.assertIsNotNone(resolution.context)
        assert resolution.context is not None
        self.assertEqual(resolution.context["project_id"], "development-platform-core")
        self.assertEqual(resolution.context["repository_root"], str(root))
        self.assertEqual(resolution.context["knowledge_root"], str(root / "vault"))
        self.assertEqual(resolution.context["planning_root"], str(root / "00-GSD-Phases"))
        self.assertTrue(resolution.context["current_objective"])
        self.assertEqual(
            resolution.provenance["objective"]["source"],
            "task_authority",
        )

    def test_valid_declaration_allows_execution(self) -> None:
        with self.project() as (root, declaration):
            resolution = self.adapter(declaration, "CURRENT").resolve_startup(
                session_id="ready-001", agent="codex"
            )

            self.assertIsInstance(resolution, StartupResolution)
            self.assertTrue(resolution.ready)
            self.assertTrue(resolution.execution_allowed)
            self.assertEqual(resolution.blocking_reasons, ())
            self.assertIsNotNone(resolution.context)
            self.assertEqual(resolution.context["current_objective"], "first task")
            self.assertEqual(resolution.context["repository_intelligence"]["status"], "CURRENT")

    def test_each_unresolved_hard_prerequisite_blocks_execution(self) -> None:
        cases = (
            ("declaration", lambda root, declaration: declaration.unlink()),
            ("canonical_roots", lambda root, declaration: (root / "plans").rmdir()),
            ("task_authority", lambda root, declaration: (root / "TODO.md").unlink()),
            ("objective", lambda root, declaration: None),
            ("task", lambda root, declaration: (root / "TODO.md").write_text("# empty\n", encoding="utf-8")),
            ("required_source", lambda root, declaration: (root / "vault/source.md").unlink()),
            ("repository_state", lambda root, declaration: None),
            ("agent", lambda root, declaration: None),
        )

        for prerequisite, mutate in cases:
            with self.subTest(prerequisite=prerequisite), self.project() as (root, declaration):
                mutate(root, declaration)
                adapter = self.adapter(declaration, "UNAVAILABLE" if prerequisite == "repository_state" else "CURRENT")
                kwargs = {"session_id": f"blocked-{prerequisite}"}
                if prerequisite == "objective":
                    kwargs["current_objective"] = ""
                if prerequisite == "agent":
                    kwargs["agent"] = "claude"
                else:
                    kwargs["agent"] = "codex"
                if prerequisite == "repository_state":
                    declaration.write_text(
                        declaration.read_text(encoding="utf-8").replace(
                            "degraded_mode: startup-without-trusted-context",
                            "degraded_mode: block",
                        ),
                        encoding="utf-8",
                    )
                    adapter = self.adapter(declaration, "DEGRADED")

                resolution = adapter.resolve_startup(**kwargs)
                self.assertFalse(resolution.ready)
                self.assertFalse(resolution.execution_allowed)
                self.assertIn(prerequisite, resolution.blocking_reasons)

    def test_degraded_repository_intelligence_follows_declaration_policy(self) -> None:
        with self.project() as (root, declaration):
            allowed = self.adapter(declaration, "DEGRADED", allow_degraded=True).resolve_startup(
                session_id="degraded-allowed", agent="codex"
            )
            denied = self.adapter(declaration, "DEGRADED", allow_degraded=False).resolve_startup(
                session_id="degraded-denied", agent="codex"
            )

            self.assertTrue(allowed.execution_allowed)
            self.assertTrue(allowed.ready)
            self.assertFalse(denied.execution_allowed)
            self.assertFalse(denied.ready)
            self.assertIn("repository_state", denied.blocking_reasons)

    def test_readiness_never_returns_contradictory_booleans(self) -> None:
        with self.project() as (root, declaration):
            for status, allow_degraded in (("CURRENT", False), ("DEGRADED", True), ("UNAVAILABLE", False)):
                resolution = self.adapter(declaration, status, allow_degraded).resolve_startup(
                    session_id=f"boolean-{status}", agent="codex"
                )
                self.assertEqual(resolution.ready, resolution.execution_allowed)

    def test_multiple_failures_are_reported_together(self) -> None:
        with self.project() as (root, declaration):
            (root / "plans").rmdir()
            (root / "TODO.md").unlink()
            (root / "vault/source.md").unlink()
            declaration.write_text(
                declaration.read_text(encoding="utf-8").replace(
                    "degraded_mode: startup-without-trusted-context", "degraded_mode: block"
                ),
                encoding="utf-8",
            )

            resolution = self.adapter(declaration, "DEGRADED").resolve_startup(
                session_id="multiple-failures", agent="claude", current_objective=""
            )

            self.assertFalse(resolution.execution_allowed)
            self.assertEqual(
                set(resolution.blocking_reasons),
                {"canonical_roots", "task_authority", "task", "objective", "agent", "required_source", "repository_state"},
            )

    def test_missing_project_id_is_a_declaration_blocker(self) -> None:
        with self.project() as (root, declaration):
            declaration.write_text(
                declaration.read_text(encoding="utf-8").replace("  id: example\n", ""),
                encoding="utf-8",
            )

            resolution = self.adapter(declaration, "CURRENT").resolve_startup(
                session_id="missing-project-id", agent="codex"
            )

            self.assertFalse(resolution.execution_allowed)
            self.assertEqual(resolution.blocking_reasons, ("declaration",))

    def test_ambiguous_agent_capability_value_is_a_declaration_blocker(self) -> None:
        with self.project() as (root, declaration):
            declaration.write_text(
                declaration.read_text(encoding="utf-8").replace(
                    "  codex: true\n", "  codex: 'false'\n"
                ),
                encoding="utf-8",
            )

            resolution = self.adapter(declaration, "CURRENT").resolve_startup(
                session_id="ambiguous-agent", agent="codex"
            )

            self.assertFalse(resolution.execution_allowed)
            self.assertEqual(resolution.blocking_reasons, ("declaration",))

    @staticmethod
    def adapter(declaration: Path, status: str, allow_degraded: bool = True) -> RadixStartupAdapter:
        def intelligence(root: Path, objective: str | None) -> dict:
            return {
                "schema": "repository-intelligence.v1",
                "status": status,
                "provider": "fake-graph",
                "generated_at": "2026-08-17T00:00:00+00:00",
                "indexed_revision": "abc123" if status in {"CURRENT", "REFRESHED"} else None,
                "trusted": status in {"CURRENT", "REFRESHED"},
                "relevant_files": [],
                "relevant_symbols": [],
                "notes": [],
                "freshness_evidence": [],
            }

        if not allow_degraded:
            declaration.write_text(
                declaration.read_text(encoding="utf-8").replace(
                    "degraded_mode: startup-without-trusted-context", "degraded_mode: block"
                ),
                encoding="utf-8",
            )
        return RadixStartupAdapter(declaration, repository_intelligence=intelligence)

    @staticmethod
    def project():
        class ProjectContext:
            def __enter__(self):
                self.temp = tempfile.TemporaryDirectory()
                root = Path(self.temp.name)
                (root / "vault").mkdir()
                (root / "plans").mkdir()
                (root / "vault/source.md").write_text("required source\n", encoding="utf-8")
                (root / "TODO.md").write_text("# tasks\n- [ ] first task\n", encoding="utf-8")
                declaration = root / "development-platform.yaml"
                declaration.write_text(
                    "schema: development-platform.v1\n"
                    "project:\n"
                    "  id: example\n"
                    "  root: .\n"
                    "  knowledge_root: vault\n"
                    "  planning_root: plans\n"
                    "repository_intelligence:\n"
                    "  enabled: true\n"
                    "  provider: code-review-graph\n"
                    "  degraded_mode: startup-without-trusted-context\n"
                    "agents:\n"
                    "  codex: true\n"
                    "  claude: false\n"
                    "gsd:\n"
                    "  enabled: true\n"
                    "  task_authority: TODO.md\n"
                    "session_brief:\n"
                    "  enabled: true\n"
                    "  source_documents: [source.md]\n",
                    encoding="utf-8",
                )
                return root, declaration

            def __exit__(self, exc_type, exc, traceback):
                self.temp.cleanup()

        return ProjectContext()


if __name__ == "__main__":
    unittest.main()
