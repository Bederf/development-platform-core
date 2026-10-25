from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from adapters.capability_projection import CapabilityProjectionError, build_skill_projection_plan


ROOT = Path(__file__).parents[1]


class CapabilityProjectionTests(unittest.TestCase):
    def test_core_source_produces_non_activating_harness_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_root = root / "skills"
            skill_root.mkdir()
            source = skill_root / "governed-engineering-loop" / "SKILL.md"
            source.parent.mkdir()
            source.write_text("# Core skill\n", encoding="utf-8")
            plan = build_skill_projection_plan(
                projection_id="gel.codex.001",
                capability_id="governed.engineering.loop",
                capability_version="1.0.0",
                source_path=source,
                core_skill_root=skill_root,
                source_identity="sha256:core-skill",
                harness_id="codex",
                adapter_id="codex.skill-loader",
                adapter_version="1.0.0",
                target_kind="skill_root",
                target_reference="client-managed",
            )
            schema = json.loads((ROOT / "contracts/capability-projection.v1.schema.json").read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(plan)
            self.assertEqual(plan["activation_policy"], "explicit_adapter_action")
            self.assertEqual(plan["status"], "planned")

    def test_projection_does_not_claim_loading_or_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "SKILL.md"
            source.write_text("# Core skill\n", encoding="utf-8")
            plan = build_skill_projection_plan(
                projection_id="gel.claude.001",
                capability_id="governed.engineering.loop",
                capability_version="1.0.0",
                source_path=source,
                core_skill_root=root,
                source_identity="sha256:core-skill",
                harness_id="claude",
                adapter_id="claude.skill-loader",
                adapter_version="1.0.0",
            )
            self.assertEqual(plan["status"], "planned")
            self.assertEqual(plan["target"], None)
            self.assertEqual(plan["activation_policy"], "consumer_managed")

    def test_source_outside_core_skill_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "outside.md"
            source.write_text("# not a Core skill\n", encoding="utf-8")
            with self.assertRaisesRegex(CapabilityProjectionError, "inside the Core skill root"):
                build_skill_projection_plan(
                    projection_id="gel.invalid.001",
                    capability_id="governed.engineering.loop",
                    capability_version="1.0.0",
                    source_path=source,
                    core_skill_root=root / "skills",
                    source_identity="sha256:outside",
                    harness_id="unknown",
                    adapter_id="unknown.skill-loader",
                    adapter_version="1.0.0",
                )
