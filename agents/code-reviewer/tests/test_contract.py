from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[3]
AGENT = ROOT / "agents" / "code-reviewer"


def test_aoc_is_read_only_and_recommendation_only() -> None:
    aoc = json.loads((AGENT / "agent-operating-contract.json").read_text())
    authority = aoc["authority"]
    assert authority["execute"] == []
    assert authority["approval_required"] is True
    assert any("read-only" in policy for policy in aoc["policies"])


def test_behavior_profile_has_five_elements_and_totals_100() -> None:
    profile = json.loads((AGENT / "agent-operating-contract.json").read_text())["behavior_profile"]
    assert len(profile["elements"]) == 5
    assert {item["name"] for item in profile["elements"]} == {"fire", "air", "earth", "water", "ether"}
    assert sum(item["points"] for item in profile["elements"]) == profile["total_points"] == 100


def test_frame_denies_mutation_and_requires_fresh_context() -> None:
    frame = json.loads((AGENT / "frame-template.json").read_text())
    assert "editing files" in frame["scope"]["out_of_scope"]
    assert "fresh context separate from implementation agent" in frame["constraints"]


def test_registration_is_inactive_and_read_only() -> None:
    text = (AGENT / "registration-proposal.yaml").read_text()
    assert "activation_status: proposed" in text
    assert "read_only: true" in text
    assert "execute: false" in text
