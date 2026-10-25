from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "vault/02-Architecture/development-platform-core.canvas"
AUTHORITY_NOTE = ROOT / "vault/02-Architecture/archify-and-obsidian-canvas-authority.md"


class CanvasGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canvas = json.loads(CANVAS.read_text(encoding="utf-8"))

    def test_canvas_is_a_source_anchored_non_authoritative_projection(self) -> None:
        nodes = self.canvas["nodes"]
        edges = self.canvas["edges"]
        node_ids = {node["id"] for node in nodes}

        self.assertEqual(len(node_ids), len(nodes))
        self.assertEqual(len({edge["id"] for edge in edges}), len(edges))
        self.assertTrue(all(edge["fromNode"] in node_ids and edge["toNode"] in node_ids for edge in edges))

        file_nodes = [node for node in nodes if node.get("type") == "file"]
        self.assertGreater(len(file_nodes), 0)
        for node in file_nodes:
            source = ROOT / node["file"]
            self.assertTrue(source.is_file(), node["file"])
        self.assertTrue(any(node["file"].startswith("docs/constitution/") for node in file_nodes))
        self.assertTrue(any(node["file"].startswith("contracts/") for node in file_nodes))

        note = AUTHORITY_NOTE.read_text(encoding="utf-8")
        self.assertIn("authority: informative", note)
        self.assertIn("Authoritative meaning", note)
        self.assertIn("must not infer runtime impact", note)


if __name__ == "__main__":
    unittest.main()
