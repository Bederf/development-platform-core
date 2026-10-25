"""Provider-free W2 enforcement-observation fixture checks."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
W1 = ROOT / "fixtures/conformance/agent-skill-capability-discovery-activation-w1.yaml"
W2 = ROOT / "fixtures/conformance/agent-skill-capability-discovery-activation-w2.yaml"


class FakeToolBroker:
    """Qualification-only enforcement double; not a Core runtime implementation."""

    def enforce(self, case: dict) -> tuple[str, int, str]:
        if case["discovery"] != "assessed":
            return "blocked_prerequisite_unavailable", 0, "unavailable discovery"
        if case["selection"] != "conformant":
            return "rejected_unresolved_binding", 0, "binding is not conformant"
        if case["activation"] != "bounded":
            return "rejected_stale_activation", 0, "activation is not current"
        if case["skill_instructions"] == "claims-approval":
            return "rejected_missing_policy", 0, "instructions are not authority"
        if case.get("evaluator_signal") and case["policy"] != "allow":
            return "rejected_missing_policy", 0, "evaluation is not authorization"
        if case["policy"] != "allow":
            return "rejected_policy_subject_mismatch", 0, "policy does not authorize dispatch"
        if case["id"] == "policy-subject-tool-mismatch":
            return "rejected_policy_subject_mismatch", 0, "policy subject does not match tool"
        return "authorized_dispatch", 1, "dispatch authorized"


def test_w2_observations_cover_every_w1_case_and_preserve_verification_gap() -> None:
    w1 = yaml.safe_load(W1.read_text(encoding="utf-8"))
    w2 = yaml.safe_load(W2.read_text(encoding="utf-8"))

    assert w2["schema"] == "agent-skill-capability-discovery-activation-enforcement.v1"
    assert w2["status"] == "candidate-qualification"
    w1_ids = {case["id"] for case in w1["cases"]}
    w2_cases = {case["id"]: case for case in w2["cases"]}
    assert set(w2_cases) == w1_ids

    blocked = {
        case_id
        for case_id, case in w2_cases.items()
        if case_id not in {"positive-one-shot-capability-dispatch", "mcp-result-is-not-verification"}
    }
    assert all(w2_cases[case_id]["adapter_dispatches"] == 0 for case_id in blocked)
    assert w2_cases["positive-one-shot-capability-dispatch"]["adapter_dispatches"] == 1
    assert w2_cases["mcp-result-is-not-verification"]["adapter_dispatches"] == 1
    assert w2_cases["mcp-result-is-not-verification"]["verification"] == "pending"


def test_fake_broker_enforces_w1_boundaries_without_authority_shortcuts() -> None:
    w1 = yaml.safe_load(W1.read_text(encoding="utf-8"))
    broker = FakeToolBroker()

    observations = {
        case["id"]: broker.enforce(case)
        for case in w1["cases"]
    }

    assert observations["positive-one-shot-capability-dispatch"][:2] == ("authorized_dispatch", 1)
    assert observations["mcp-result-is-not-verification"][:2] == ("authorized_dispatch", 1)
    for case_id, (observation, dispatches, _reason) in observations.items():
        if case_id not in {
            "positive-one-shot-capability-dispatch",
            "mcp-result-is-not-verification",
        }:
            assert dispatches == 0, case_id
            assert observation != "authorized_dispatch", case_id


def test_w2_edge_cases_preserve_dispatch_and_failure_distinctions() -> None:
    document = yaml.safe_load(W2.read_text(encoding="utf-8"))
    edge_cases = {case["id"]: case for case in document["edge_cases"]}
    expected_ids = {
        "arguments-digest-mismatch",
        "revoked-policy",
        "expired-policy",
        "broker-state-unavailable",
        "duplicate-retry-attempt",
        "bounded-retry-new-attempt",
        "adapter-timeout",
        "partial-effect",
    }
    assert set(edge_cases) == expected_ids

    blocked = {
        "arguments-digest-mismatch",
        "revoked-policy",
        "expired-policy",
        "broker-state-unavailable",
        "duplicate-retry-attempt",
    }
    for case_id in blocked:
        case = edge_cases[case_id]
        assert case["adapter_dispatches"] == 0
        assert case["expected_execution"] in {"not_run", "unknown"}

    assert edge_cases["bounded-retry-new-attempt"]["predecessor_preserved"] is True
    assert edge_cases["adapter-timeout"]["expected_execution"] == "timeout"
    assert edge_cases["partial-effect"]["expected_execution"] == "partial"
    assert edge_cases["adapter-timeout"]["verification"] == "pending"
    assert edge_cases["partial-effect"]["verification"] == "pending"


def test_w2_adversarial_cases_block_shortcuts_and_preserve_evidence_authority() -> None:
    document = yaml.safe_load(W2.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in document["adversarial_cases"]}
    assert set(cases) == {
        "direct-mcp-bypass",
        "provider-forged-policy-allow",
        "provider-expands-activated-tool-surface",
        "discovery-injects-credential",
        "forged-evidence-from-transport",
    }

    for case_id in set(cases) - {"forged-evidence-from-transport"}:
        assert cases[case_id]["adapter_dispatches"] == 0
        assert cases[case_id]["expected_execution"] == "not_run"

    forged_evidence = cases["forged-evidence-from-transport"]
    assert forged_evidence["adapter_dispatches"] == 1
    assert forged_evidence["expected_execution"] == "completed"
    assert forged_evidence["verification"] == "pending"
