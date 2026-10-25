"""Contract-level checks for the project onboarding boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_onboarding_contract_is_versioned_and_keeps_integrations_unqualified() -> None:
    document = (ROOT / "docs/specifications/PROJECT-ONBOARDING-CONTRACT-v1.md").read_text(
        encoding="utf-8"
    )

    assert "# Project Onboarding Contract v1" in document
    assert "Optional integrations use the same lifecycle" in document
    assert "qualification" in document
    assert "explicit developer" in document


def test_humanizer_bootstrap_is_explicitly_dormant() -> None:
    policy = (ROOT / "templates/humanizer-v0.5/config/humanizer/policy.yaml").read_text(
        encoding="utf-8"
    )
    bootstrap = (ROOT / "scripts/init-humanizer-v05.sh").read_text(encoding="utf-8")

    assert "enabled: false" in policy
    assert "qualification_status: pending" in policy
    assert "never qualifies" not in bootstrap
    assert "dormant" in bootstrap.lower()


def test_onboarding_contract_does_not_create_a_second_authority_manifest() -> None:
    document = (ROOT / "docs/specifications/PROJECT-ONBOARDING-CONTRACT-v1.md").read_text(
        encoding="utf-8"
    )

    assert "second source" in document
    assert "project authority" in document
    assert "development-platform.yaml" in document
    assert "does not replace `development-platform.yaml`" in document
