"""Provider-free W1 qualification fixture for agent/skill activation boundaries."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures/conformance/agent-skill-capability-discovery-activation-w1.yaml"


def test_w1_fixture_covers_required_authority_and_failure_boundaries() -> None:
    document = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert document["schema"] == "agent-skill-capability-discovery-activation-conformance.v1"
    assert document["status"] == "candidate-qualification"

    cases = {case["id"]: case for case in document["cases"]}
    required = {
        "positive-one-shot-capability-dispatch",
        "discovery-is-not-conformance",
        "unselected-capability",
        "skill-instruction-cannot-authorize",
        "policy-subject-tool-mismatch",
        "stale-activation",
        "unavailable-discovery",
        "jev-score-is-not-authorization",
        "mcp-result-is-not-verification",
    }
    assert set(cases) == required

    positive = cases["positive-one-shot-capability-dispatch"]
    assert positive["policy"] == "allow"
    assert positive["broker"] == "dispatch"
    assert positive["execution"] == "completed"

    for case_id in required - {
        "positive-one-shot-capability-dispatch",
        "mcp-result-is-not-verification",
    }:
        case = cases[case_id]
        assert case["broker"] == "block"
        assert case["execution"] == "not_run"

    assert cases["skill-instruction-cannot-authorize"]["policy"] == "absent"
    assert cases["jev-score-is-not-authorization"]["policy"] == "absent"
    assert cases["mcp-result-is-not-verification"]["broker"] == "dispatch"
    assert cases["mcp-result-is-not-verification"]["execution"] == "completed"
    assert cases["mcp-result-is-not-verification"]["verification"] == "required"
