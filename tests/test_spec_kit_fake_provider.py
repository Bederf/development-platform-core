from __future__ import annotations

import pytest

from adapters.spec_kit_fake_provider import FakeSpecKitProvider
from adapters.spec_kit_mapping import SpecKitMappingError


def test_fake_provider_emits_core_shaped_specification_and_plan() -> None:
    provider = FakeSpecKitProvider()
    specification = provider.emit(
        "/specify", artifact_ref="spec-001", digest="sha256:spec", evidence_refs=["intent-001"]
    )
    plan = provider.emit(
        "/plan", artifact_ref="plan-001", digest="sha256:plan", evidence_refs=["spec-001"]
    )
    assert specification["proposal"]["artifact"]["stage"] == "SPECIFICATION"
    assert plan["proposal"]["artifact"]["kind"] == "plan"
    assert specification["proposal"]["authority"] == "provider_proposal"


def test_implement_requires_task_traceability() -> None:
    provider = FakeSpecKitProvider()
    with pytest.raises(ValueError):
        provider.emit("/implement", artifact_ref="impl-001", digest="sha256:impl")
    report = provider.emit(
        "/implement", artifact_ref="impl-001", digest="sha256:impl", task_refs=["task-001"]
    )
    assert report["report_type"] == "implementation"


def test_speckit_aliases_preserve_specialized_behavior() -> None:
    provider = FakeSpecKitProvider()
    report = provider.emit(
        " /speckit.implement ",
        artifact_ref="impl-alias-001",
        digest="sha256:impl-alias",
        task_refs=["task-001"],
    )
    assert report["report_type"] == "implementation"

    remediation = provider.emit(
        "/speckit.converge",
        artifact_ref="remediation-alias-001",
        digest="sha256:remediation-alias",
        requirements_complete=False,
        evidence_refs=["implementation-001"],
    )
    assert remediation["artifact_proposal"]["artifact"]["kind"] == "remediation"


def test_converge_reports_remediation_without_acceptance() -> None:
    provider = FakeSpecKitProvider()
    result = provider.emit(
        "/converge",
        artifact_ref="remediation-001",
        digest="sha256:remediation",
        requirements_complete=False,
        evidence_refs=["implementation-001"],
    )
    assert result["artifact_proposal"]["artifact"]["kind"] == "remediation"
    assert not hasattr(provider, "accept")
    assert not hasattr(provider, "verify")


def test_spec_kit_cannot_emit_verification_or_acceptance() -> None:
    provider = FakeSpecKitProvider()
    for operation, kind in (("independent_verification", "verification"), ("acceptance", "acceptance")):
        with pytest.raises(SpecKitMappingError):
            provider.emit(operation, artifact_ref=f"{kind}-001", digest=f"sha256:{kind}")
