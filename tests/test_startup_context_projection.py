from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver

from adapters.radix.context_projection import (
    ContextProjectionError,
    StartupContextProjector,
    extract_active_actions,
)
from adapters.radix.context_projection_cli import main as projection_main


ROOT = Path(__file__).parents[1]
CONTRACTS = ROOT / "contracts"


def write_declaration(root: Path, project_id: str) -> None:
    (root / "vault").mkdir(exist_ok=True)
    (root / "phases").mkdir(exist_ok=True)
    (root / "TODO.md").write_text("- [ ] project-owned task\n", encoding="utf-8")
    (root / "development-platform.yaml").write_text(
        "schema: development-platform.v1\n"
        "project:\n"
        f"  id: {project_id}\n"
        "  root: .\n"
        "  knowledge_root: vault\n"
        "  planning_root: phases\n"
        "repository_intelligence:\n"
        "  enabled: false\n"
        "  degraded_mode: startup-without-trusted-context\n"
        "agents:\n"
        "  codex: true\n"
        "gsd:\n"
        "  enabled: true\n"
        "  task_authority: TODO.md\n",
        encoding="utf-8",
    )


def section(
    section_id: str,
    text: str,
    *,
    kind: str = "active",
    authority: str = "executable",
    mandatory: bool = False,
) -> dict[str, object]:
    return {
        "source_id": "control",
        "path": "/project/control.md",
        "section_id": section_id,
        "kind": kind,
        "authority": authority,
        "text": text,
        "content_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        "mandatory": mandatory,
    }


class StartupContextProjectionConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.projector = StartupContextProjector(max_tokens=6000)

    def test_projection_is_schema_valid_and_compact_by_default(self) -> None:
        projection = self.projector.project(
            project_id="example",
            objective="implement premise staleness",
            tasks=[
                {"id": "onboarding", "description": "assertion discovery governance"},
                {"id": "recommendations", "description": "recommendation premise staleness"},
            ],
            brief={"status": "accepted", "path": "/vault/session-brief.md", "text": "Current work only."},
            sections=[
                section("active", "Premise staleness is the current implementation gap."),
                section("history", "Phase 100 closed long ago.", kind="history"),
                section("versions", "## Version History\nold phase records", kind="history"),
            ],
            source_documents=[
                {"source_id": "memory", "path": "/vault/MEMORY.md"},
                {"source_id": "todo", "path": "/vault/TODO.md"},
            ],
        )

        schema = json.loads(
            (CONTRACTS / "startup-context-projection.v1.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(
            schema, resolver=RefResolver((CONTRACTS / "startup-context-projection.v1.schema.json").as_uri(), schema)
        ).validate(projection)
        self.assertEqual(projection["task_selection"]["task_id"], "recommendations")
        self.assertEqual([item["section_id"] for item in projection["inline_sections"]], ["active"])
        self.assertLessEqual(projection["budget"]["estimated_tokens"], 6000)
        self.assertEqual(
            {item["source_id"] for item in projection["on_demand_sources"]},
            {"memory", "todo", "control"},
        )
        self.assertIsNone(projection["working_state"])

    def test_projection_carries_derived_working_state_only(self) -> None:
        from providers.working_state import WorkingStateProvider

        with tempfile.TemporaryDirectory() as directory:
            provider = WorkingStateProvider(project_id="example", checkpoint_path=Path(directory) / "state.json")
            state = provider.create(
                session_id="session-2",
                gsd={"ref": "gsd:1", "objective": "implement X", "phase": 3, "next": "E", "blocker": "none"},
                session_records=[{"ref": "session:1", "discoveries": ["C"], "failures": ["D"]}],
                reason="handoff",
                summaries={"completed": ["A", "B"], "discoveries": ["C"], "failures": ["D"]},
            )
            projection = self.projector.project(
                project_id="example",
                objective="implement X",
                tasks=[],
                brief={"status": "unavailable", "path": None, "text": None},
                sections=[],
                source_documents=[],
                working_state=state,
            )
            self.assertEqual(projection["working_state"]["next_step"], "E")
            self.assertIn("orientation only", self.projector.render_prompt(projection))

    def test_no_unrelated_task_is_used_as_a_default(self) -> None:
        projection = self.projector.project(
            project_id="example",
            objective="repair release signing",
            tasks=[{"id": "onboarding", "description": "assertion discovery governance"}],
            brief={"status": "accepted", "path": "/brief.md", "text": "Release signing."},
            sections=[],
            source_documents=[],
        )
        self.assertIsNone(projection["task_selection"]["task_id"])

    def test_duplicate_text_is_inlined_once(self) -> None:
        shared = section("one", "Current authority for the objective.")
        duplicate = dict(shared, section_id="two", path="/project/duplicate.md")
        projection = self.projector.project(
            project_id="example",
            objective="current authority",
            tasks=[],
            brief={"status": "unavailable", "path": None, "text": None},
            sections=[shared, duplicate],
            source_documents=[],
        )
        self.assertEqual(len(projection["inline_sections"]), 1)

    def test_budget_moves_overflow_to_on_demand_instead_of_overfilling(self) -> None:
        projector = StartupContextProjector(max_tokens=40)
        projection = projector.project(
            project_id="example",
            objective="bounded context",
            tasks=[],
            brief={"status": "accepted", "path": "/brief.md", "text": "brief"},
            sections=[
                section("required", "required authority", mandatory=True),
                section("large", "bounded context " * 100),
            ],
            source_documents=[],
        )
        self.assertLessEqual(projection["budget"]["estimated_tokens"], 40)
        self.assertTrue(projection["budget"]["truncated"])
        self.assertTrue(any(item["reason"] == "context budget" for item in projection["on_demand_sources"]))

    def test_oversized_brief_fails_closed(self) -> None:
        with self.assertRaises(ContextProjectionError):
            StartupContextProjector(max_tokens=10).project(
                project_id="example",
                objective="bounded context",
                tasks=[],
                brief={"status": "accepted", "path": "/brief.md", "text": "x" * 100},
                sections=[],
                source_documents=[],
            )

    def test_closed_heading_filter_is_case_insensitive(self) -> None:
        text = (
            "### ✅ closed 2026-01-01 — old phase\n"
            "**Next action:** obsolete action\n\n"
            "### Active delivery\n"
            "**Next action:** current action\n"
        )
        self.assertEqual(extract_active_actions(text), ["current action"])

    def test_terminal_status_in_body_is_not_routed(self) -> None:
        text = (
            "### Old phase without a closed heading\n"
            "**Status:** Complete, retained for history\n"
            "**Next action:** obsolete action\n\n"
            "### Current phase\n"
            "**Status:** Pending\n"
            "**Next action:** current action\n"
        )
        self.assertEqual(extract_active_actions(text), ["current action"])

    def test_prompt_uses_compact_context_and_on_demand_references(self) -> None:
        projection = self.projector.project(
            project_id="example",
            objective="ship compact startup",
            tasks=[],
            brief={"status": "accepted", "path": "/brief.md", "text": "Current compact summary."},
            sections=[section("authority", "Only current authority is inline.", mandatory=True)],
            source_documents=[{"source_id": "history", "path": "/vault/MEMORY.md"}],
        )
        prompt = self.projector.render_prompt(projection)
        self.assertIn("Current compact summary.", prompt)
        self.assertIn("Only current authority is inline.", prompt)
        self.assertIn("Load only when the task requires it", prompt)
        self.assertNotIn("Read and follow these sources in order", prompt)

    def test_cli_binds_projection_to_discovered_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_declaration(root, "bound-project")
            payload = root / "projection.json"
            payload.write_text(
                json.dumps(
                    {
                        "project_id": "bound-project",
                        "objective": "bounded startup",
                        "tasks": [],
                        "brief": {"status": "accepted", "path": "/brief.md", "text": "Brief."},
                        "sections": [],
                        "source_documents": [],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                result = projection_main(
                    ["--project", str(root), "--input", str(payload), "--format", "json"]
                )
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())["project_id"], "bound-project")

    def test_cli_rejects_foreign_project_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_declaration(root, "bound-project")
            payload = root / "projection.json"
            payload.write_text(
                json.dumps({"project_id": "foreign", "objective": "bounded startup"}),
                encoding="utf-8",
            )
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = projection_main(["--project", str(root), "--input", str(payload)])
            self.assertEqual(result, 2)
            self.assertIn("another project", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
