"""Disposable fake-provider qualification harness for delegation.v1.

This is deliberately test-only. It does not call providers, tools, Herdr,
Forge, or production runtime code.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]


def digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def ref(semantic_type: str, identifier: str, scope: str = "fixture-project") -> dict[str, str]:
    return {
        "semantic_type": semantic_type,
        "id": identifier,
        "version": "1.0.0",
        "digest": "sha256:" + "a" * 64,
        "scope_ref": scope,
    }


def execution(identifier: str) -> dict[str, str]:
    return {
        "semantic_type": "agent_execution",
        "id": identifier,
        "version": "1.0.0",
        "digest": "sha256:" + "b" * 64,
    }


def base(entity_type: str, identifier: str, entity: dict[str, Any]) -> dict[str, Any]:
    record = {
        "schema": "delegation.v1",
        "entity_type": entity_type,
        "entity_id": identifier,
        "version": "1.0.0",
        "delegation_id": "D1",
        "revision": 1,
        "scope": {"scope_type": "project", "scope_id": "fixture-project"},
        "lineage": [ref("gsd_task", "T1")],
        "digest": "sha256:" + "c" * 64,
        "created_at": "2026-09-02T10:00:00Z",
    }
    record.update(entity)
    return record


def child(identifier: str, status: str = "VERIFIED", revision: int = 1) -> dict[str, Any]:
    return base(
        "delegation_child",
        identifier,
        {
            "entity_type": "delegation_child",
            "child_id": identifier,
            "expected_role": "coding-worker",
            "parent_ref": {
                "semantic_type": "delegation_set",
                "id": "D1",
                "version": "1.0.0",
                "digest": "sha256:" + "d" * 64,
            },
            "instruction_ref": ref("instruction", f"I-{identifier}"),
            "instruction_digest": "sha256:" + "e" * 64,
            "context_ref": ref("context", f"C-{identifier}"),
            "context_digest": "sha256:" + "f" * 64,
            "child_execution_ref": execution(f"E-{identifier}"),
            "result_refs": [ref("evidence_record", f"R-{identifier}")],
            "status": status,
            **({"revision": revision} if revision != 1 else {}),
        },
    )


def aggregation(statuses: dict[str, str]) -> dict[str, Any]:
    ids = list(statuses)
    def child_refs() -> list[dict[str, str]]:
        return [
            {
                "semantic_type": "delegation_child",
                "id": identifier,
                "version": "1.0.0",
                "digest": "sha256:" + "d" * 64,
            }
            for identifier in ids
        ]
    refs = child_refs()
    blocking = [identifier for identifier, status in statuses.items() if status != "VERIFIED"]
    return base(
        "aggregation",
        "A1",
        {
            "entity_type": "aggregation",
            "parent_ref": {
                "semantic_type": "delegation_set",
                "id": "D1",
                "version": "1.0.0",
                "digest": "sha256:" + "d" * 64,
            },
            "expected_child_refs": refs,
            "observed_child_refs": list(refs),
            "included_child_refs": list(refs),
            "unknown_children": [identifier for identifier in blocking if statuses[identifier] == "UNKNOWN"],
            "partial_children": [identifier for identifier in blocking if statuses[identifier] == "PARTIAL"],
            "failed_children": [identifier for identifier in blocking if statuses[identifier] == "FAILED"],
            "timed_out_children": [identifier for identifier in blocking if statuses[identifier] == "TIMED_OUT"],
            "cancelled_children": [identifier for identifier in blocking if statuses[identifier] == "CANCELLED"],
            "aggregation_status": status_for(statuses),
        },
    )


def status_for(statuses: dict[str, str]) -> str:
    if not statuses:
        return "UNKNOWN"
    if any(status == "UNKNOWN" for status in statuses.values()):
        return "UNKNOWN"
    if all(status == "VERIFIED" for status in statuses.values()):
        return "COMPLETE"
    return "PARTIAL"


def derive_aggregation(
    expected: set[str],
    observed: set[str],
    included: set[str],
    statuses: dict[str, str],
) -> dict[str, Any]:
    """Test-only semantic evaluator for the candidate conformance profile."""
    missing = expected - observed
    unexpected = observed - expected
    omitted = observed - included
    invalid_included = included - observed
    unsafe = {"UNKNOWN", "PARTIAL", "FAILED", "TIMED_OUT", "CANCELLED", "BLOCKED"}
    reasons: set[str] = set()
    if missing:
        reasons.add("MISSING_EXPECTED_CHILD")
    if unexpected:
        reasons.add("UNEXPECTED_CHILD")
    if omitted:
        reasons.add("OBSERVED_NOT_INCLUDED")
    if invalid_included:
        reasons.add("INCLUDED_NOT_OBSERVED")
    if any(statuses.get(child) in unsafe for child in expected):
        reasons.add("UNSAFE_CHILD_STATUS")
    status = "COMPLETE" if not reasons and expected == observed == included else "BLOCKED"
    return {
        "status": status,
        "missing": missing,
        "unexpected": unexpected,
        "omitted": omitted,
        "invalid_included": invalid_included,
        "reasons": reasons,
    }


class GovernedDelegationReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads((ROOT / "contracts/delegation.v1.candidate.schema.json").read_text())
        cls.validator = Draft202012Validator(schema)

    def test_fake_provider_records_validate_and_round_trip(self) -> None:
        records = [
            base(
                "delegation_set",
                "D1",
                {
                    "entity_type": "delegation_set",
                    "parent_task_ref": ref("gsd_task", "T1"),
                    "objective_ref": ref("objective", "O1"),
                    "objective_digest": "sha256:" + "0" * 64,
                    "authority_scope_ref": ref("authority_scope", "S1"),
                    "required_capability_refs": [ref("capability", "capability-a")],
                    "budget_ref": ref("delegation_budget", "B1"),
                    "deadline": "2026-09-02T11:00:00Z",
                    "parent_execution_ref": execution("P1"),
                    "expected_children": ["A", "B", "C"],
                    "expected_set_digest": "sha256:" + "1" * 64,
                    "status": "OPEN",
                },
            ),
            child("A"),
            aggregation({"A": "VERIFIED", "B": "VERIFIED", "C": "VERIFIED"}),
        ]
        for record in records:
            self.validator.validate(record)
            self.assertEqual(json.loads(json.dumps(record, sort_keys=True)), record)

    def test_canonical_digest_is_independently_reproducible(self) -> None:
        payload = {"context": {"b": 2, "a": 1}, "instruction": "inspect"}
        first = digest(payload)
        second = digest(json.loads(json.dumps(payload)))
        self.assertEqual(first, second)
        self.assertNotEqual(first, digest({**payload, "instruction": "mutate"}))

    def test_unknown_expected_child_blocks_parent_completion(self) -> None:
        result = aggregation({"A": "VERIFIED", "B": "VERIFIED", "C": "UNKNOWN"})
        self.assertEqual(result["aggregation_status"], "UNKNOWN")
        self.assertNotEqual(result["aggregation_status"], "COMPLETE")

    def test_status_and_scope_rules_are_fail_closed(self) -> None:
        for status in ("PARTIAL", "FAILED", "TIMED_OUT", "CANCELLED"):
            result = aggregation({"A": "VERIFIED", "B": status, "C": "VERIFIED"})
            self.assertNotEqual(result["aggregation_status"], "COMPLETE")
        record = aggregation({"A": "VERIFIED", "B": "VERIFIED", "C": "VERIFIED"})
        record["scope"]["scope_id"] = "other-project"
        self.assertNotEqual(record["scope"]["scope_id"], "fixture-project")

    def test_revision_change_does_not_overwrite_prior_attempt(self) -> None:
        first = child("B", "FAILED")
        second = child("B", "VERIFIED", revision=2)
        self.assertEqual(first["revision"], 1)
        self.assertEqual(second["revision"], 2)
        self.assertNotEqual(first["revision"], second["revision"])
        self.assertEqual(first["instruction_digest"], second["instruction_digest"])

    def test_provider_names_are_opaque_to_core_semantics(self) -> None:
        for provider in ("fake-codex", "fake-claude", "fake-api-x"):
            record = aggregation({"A": "VERIFIED", "B": "VERIFIED", "C": "VERIFIED"})
            record["provider"] = provider
            self.assertTrue(list(self.validator.iter_errors(record)))
            record.pop("provider")
            self.assertFalse(list(self.validator.iter_errors(record)))
            self.assertEqual(status_for({"A": "VERIFIED", "B": "VERIFIED", "C": "VERIFIED"}), "COMPLETE")

    def test_schema_requires_objective_scope_capability_budget_and_deadline(self) -> None:
        record = base(
            "delegation_set",
            "D1",
            {
                "entity_type": "delegation_set",
                "parent_task_ref": ref("gsd_task", "T1"),
                "parent_execution_ref": execution("P1"),
                "expected_children": ["A"],
                "expected_set_digest": "sha256:" + "1" * 64,
                "status": "OPEN",
            },
        )
        errors = list(self.validator.iter_errors(record))
        self.assertTrue(errors)

    def test_timeout_is_not_success(self) -> None:
        result = aggregation({"A": "VERIFIED", "B": "TIMED_OUT", "C": "VERIFIED"})
        self.assertEqual(result["timed_out_children"], ["B"])
        self.assertEqual(result["aggregation_status"], "PARTIAL")
        self.assertNotEqual(result["aggregation_status"], "COMPLETE")

    def test_retry_is_one_expected_child_with_preserved_attempts(self) -> None:
        first = child("B", "FAILED")
        second = child("B", "VERIFIED", revision=2)
        second["previous_attempt_ref"] = first["child_execution_ref"]
        expected = {"B"}
        observed = {second["child_id"]}
        self.assertEqual(expected, observed)
        self.assertEqual(second["previous_attempt_ref"], first["child_execution_ref"])

    def test_expected_observed_included_sets_fail_closed(self) -> None:
        result = derive_aggregation({"A", "B", "C"}, {"A", "B"}, {"A", "B"}, {"A": "VERIFIED", "B": "VERIFIED"})
        self.assertEqual(result["missing"], {"C"})
        self.assertEqual(result["status"], "BLOCKED")

        result = derive_aggregation({"A", "B"}, {"A", "B", "X"}, {"A", "B"}, {"A": "VERIFIED", "B": "VERIFIED", "X": "VERIFIED"})
        self.assertEqual(result["unexpected"], {"X"})
        self.assertEqual(result["status"], "BLOCKED")

        result = derive_aggregation({"A", "B"}, {"A"}, {"A", "B"}, {"A": "VERIFIED"})
        self.assertEqual(result["invalid_included"], {"B"})
        self.assertIn("INCLUDED_NOT_OBSERVED", result["reasons"])

    def test_observed_but_omitted_and_status_laundering_fail(self) -> None:
        result = derive_aggregation({"A", "B"}, {"A", "B"}, {"A"}, {"A": "VERIFIED", "B": "VERIFIED"})
        self.assertEqual(result["omitted"], {"B"})
        self.assertEqual(result["status"], "BLOCKED")

        for status in ("FAILED", "TIMED_OUT", "CANCELLED", "PARTIAL", "UNKNOWN"):
            result = derive_aggregation({"A", "B"}, {"A", "B"}, {"A", "B"}, {"A": "VERIFIED", "B": status})
            with self.subTest(status=status):
                self.assertNotEqual(result["status"], "COMPLETE")

    def test_aggregation_completion_does_not_establish_authority(self) -> None:
        result = derive_aggregation({"A"}, {"A"}, {"A"}, {"A": "VERIFIED"})
        self.assertEqual(result["status"], "COMPLETE")
        self.assertNotIn("contract_authoritative", result)


if __name__ == "__main__":
    unittest.main()
