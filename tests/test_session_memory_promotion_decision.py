"""Evidence checks for the deferred session-memory promotion decision."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "docs/assurance/SESSION-MEMORY-PROMOTION-DECISION-v1.md"


def test_session_memory_promotion_is_deferred_until_live_retrieval_evidence() -> None:
    text = DECISION.read_text(encoding="utf-8")
    assert 'status: "deferred"' in text
    assert "**DEFER** creation of a promoted `session-memory.v1` contract." in text
    assert "real admitted redacted records" in text
    assert "live retrieval provider" in text


def test_decision_preserves_the_authority_boundary() -> None:
    text = DECISION.read_text(encoding="utf-8")
    assert "not a semantic historical search system" in text
    assert "must not be relabelled" in text
    assert "promoted memory database" in text
