"""Provider substitution must preserve platform-owned verified outcomes."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from tests.test_contracts import validate
from tests.test_tool_mediation_contract_linkage import (
    assert_execution_linkage,
    build_chain,
)

ROOT = Path(__file__).parents[1]


class Provider:
    def __init__(self, provider_id: str, proposal: dict[str, str]) -> None:
        self.provider_id = provider_id
        self.proposal = proposal

    def propose(self, capability: dict[str, str]) -> dict[str, str]:
        return {**self.proposal, "provider": self.provider_id}


def run_platform(
    capability: dict[str, str],
    provider: Provider,
    *,
    authorization: str,
    verification: str,
) -> dict[str, str | None]:
    proposal = provider.propose(capability)
    if proposal["operation"] != capability["operation"] or proposal["target"] != capability["target"]:
        return {"state": "UNVERIFIED", "transition": None}
    if authorization != "allow":
        return {"state": "UNVERIFIED", "transition": None}
    if verification != "pass":
        return {"state": "UNVERIFIED", "transition": None}
    return {"state": "VERIFIED", "transition": capability["expected_transition"]}


def typed_execution_chain(provider: Provider) -> dict[str, dict]:
    """Project a provider proposal into the existing typed execution chain."""
    chain = deepcopy(build_chain())
    arguments = {"path": "document://example", "content": provider.proposal["content"]}
    argument_digest = f"sha256:{provider.provider_id.replace('.', '-')}-arguments"
    for entity in ("proposal", "authorized_request"):
        chain[entity]["arguments"] = arguments
        chain[entity]["arguments_digest"] = argument_digest
    chain["execution_result"]["arguments_digest"] = argument_digest
    return chain


def test_provider_substitution_preserves_verified_transition() -> None:
    fixture = yaml.safe_load(
        (ROOT / "fixtures/conformance/provider-equivalence-v1.yaml").read_text()
    )
    capability = fixture["capability"]
    providers = [Provider(item["id"], item["proposal"]) for item in fixture["providers"]]

    outcomes = [
        run_platform(capability, provider, authorization="allow", verification="pass")
        for provider in providers
    ]

    assert providers[0].proposal["content"] != providers[1].proposal["content"]
    for provider in providers:
        chain = typed_execution_chain(provider)
        validate("engineering-execution.v1.schema.json", chain["proposal"])
        validate("engineering-execution.v1.schema.json", chain["authorized_request"])
        validate("engineering-execution.v1.schema.json", chain["execution_result"])
        validate("verification-result.v1.schema.json", chain["verification"])
        assert_execution_linkage(chain)
    assert outcomes == [
        {"state": "VERIFIED", "transition": "document://example@revision-2"},
        {"state": "VERIFIED", "transition": "document://example@revision-2"},
    ]


def test_provider_proposal_cannot_create_authority_or_verification() -> None:
    fixture = yaml.safe_load(
        (ROOT / "fixtures/conformance/provider-equivalence-v1.yaml").read_text()
    )
    capability = fixture["capability"]
    provider = Provider(fixture["providers"][0]["id"], fixture["providers"][0]["proposal"])

    denied = run_platform(capability, provider, authorization="deny", verification="not_run")
    unavailable = run_platform(capability, provider, authorization="allow", verification="unavailable")

    assert denied == {"state": "UNVERIFIED", "transition": None}
    assert unavailable == {"state": "UNVERIFIED", "transition": None}


def test_operation_metadata_is_representable_in_existing_capability_family() -> None:
    definition = json.loads(
        (ROOT / "capabilities/governed-engineering-loop.v1.0.0.json").read_text()
    )
    definition["operation_descriptors"] = [{
        "operation_id": "execute",
        "input_contracts": [{"semantic_type": "engineering-execution", "id": "engineering-execution.v1", "version": "1.0.0"}],
        "output_contracts": [{"semantic_type": "verification-result", "id": "verification-result.v1", "version": "1.0.0"}],
        "authority_requirements": [{"semantic_type": "policy-decision", "id": "policy-decision.v1", "version": "1.0.0"}],
        "side_effect_classification": "state_change",
        "idempotency": "conditionally_idempotent",
        "verification_strategy": {"semantic_type": "verification-strategy", "id": "independent-checks", "version": "1.0.0"},
        "supported_implementations": [{"semantic_type": "implementation_descriptor", "id": "provider.alpha", "version": "1.0.0"}],
    }]
    schema = json.loads(
        (ROOT / "contracts/capability-definition.v1.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(definition)
