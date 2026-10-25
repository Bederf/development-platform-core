from __future__ import annotations

import unittest

from capabilities.governed_delegation_conformance import canonical_digest, evaluate


def ref(identifier: str, scope: str = "project-a") -> dict[str, str]:
    return {"semantic_type": "ref", "id": identifier, "version": "1.0.0", "digest": "sha256:" + "a" * 64, "scope_ref": scope}


def base_set(expected: list[str]) -> dict:
    return {
        "delegation_id": "D1",
        "version": "1.0.0",
        "revision": 1,
        "scope": {"scope_type": "project", "scope_id": "project-a"},
        "objective_ref": ref("objective-1"),
        "objective_digest": canonical_digest({"goal": "inspect"}),
        "authority_scope_ref": ref("scope-1"),
        "required_capability_refs": [ref("capability-a")],
        "budget_ref": ref("budget-1"),
        "deadline": "2026-09-18T12:00:00Z",
        "expected_children": expected,
        "expected_set_digest": canonical_digest(sorted(expected)),
    }


def child(identifier: str, status: str = "SUCCEEDED", revision: int = 1, scope: str = "project-a", result_id: str | None = None) -> dict:
    return {
        "delegation_id": "D1",
        "revision": revision,
        "scope": {"scope_type": "project", "scope_id": scope},
        "child_id": identifier,
        "parent_ref": {"id": "D1", "version": "1.0.0"},
        "status": status,
        "result_refs": ([ref(result_id or f"result-{identifier}")] if result_id is not None or status in {"SUCCEEDED", "VERIFIED"} else []),
    }


def aggregate(ids: list[str]) -> dict:
    refs = [ref(identifier) for identifier in ids]
    return {
        "expected_child_refs": refs,
        "observed_child_refs": refs,
        "included_child_refs": refs,
        "aggregation_status": "COMPLETE",
    }


def result_record(result_id: str, child_id: str, *, outcome_digest: str | None = None, revision: int | None = None) -> dict:
    value = {"child_id": child_id, "digest": ref(result_id)["digest"], "outcome_digest": outcome_digest or "sha256:" + "0" * 64}
    if revision is not None:
        value["revision"] = revision
    return value


def resolved_scopes() -> dict[str, dict[str, str]]:
    return {"scope-1": {"scope_type": "project", "scope_id": "project-a"}}


class GovernedDelegationConformanceTests(unittest.TestCase):
    def test_clean_records_complete_only_as_non_authoritative_fact(self) -> None:
        records = {("result-A", "1.0.0"): result_record("result-A", "A", outcome_digest="sha256:" + "1" * 64)}
        result = evaluate(base_set(["A"]), [child("A", result_id="result-A")], aggregate(["A"]), objective_payloads={"objective-1": {"goal": "inspect"}}, available_capabilities={"capability-a"}, authority_scope_payloads=resolved_scopes(), as_of="2026-09-18T11:00:00Z", result_records=records)
        self.assertEqual(result.status, "COMPLETE")

    def test_objective_digest_mismatch_blocks(self) -> None:
        delegation = base_set(["A"])
        delegation["objective_digest"] = canonical_digest({"goal": "tampered"})
        result = evaluate(delegation, [child("A", result_id="result-A")], aggregate(["A"]), objective_payloads={"objective-1": {"goal": "inspect"}}, result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertIn("OBJECTIVE_DIGEST_INVALID", {finding.code for finding in result.findings})

    def test_expected_set_digest_mismatch_blocks(self) -> None:
        delegation = base_set(["A"])
        delegation["expected_set_digest"] = canonical_digest(["B"])
        result = evaluate(delegation, [child("A", result_id="result-A")], aggregate(["A"]), result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertIn("EXPECTED_SET_DIGEST_INVALID", {finding.code for finding in result.findings})

    def test_missing_capability_blocks(self) -> None:
        result = evaluate(base_set(["A"]), [child("A", result_id="result-A")], aggregate(["A"]), available_capabilities=set(), result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertIn("CAPABILITY_REQUIREMENT_UNSATISFIED", {finding.code for finding in result.findings})

    def test_scope_expansion_blocks(self) -> None:
        result = evaluate(base_set(["A"]), [child("A", scope="project-b")], aggregate(["A"]), result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertIn("CHILD_SCOPE_INVALID", {finding.code for finding in result.findings})

    def test_stale_revision_blocks(self) -> None:
        result = evaluate(base_set(["A"]), [child("A", revision=2)], aggregate(["A"]), result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertIn("REVISION_BINDING_INVALID", {finding.code for finding in result.findings})

    def test_duplicate_child_observation_blocks(self) -> None:
        result = evaluate(base_set(["A"]), [child("A"), child("A")], aggregate(["A"]), result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertIn("DUPLICATE_CHILD", {finding.code for finding in result.findings})

    def test_stale_result_revision_blocks(self) -> None:
        result = evaluate(
            base_set(["A"]),
            [child("A", result_id="result-A")],
            aggregate(["A"]),
            result_records={("result-A", "1.0.0"): result_record("result-A", "A", revision=99)},
        )
        self.assertIn("RESULT_REVISION_INVALID", {finding.code for finding in result.findings})

    def test_wrong_child_evidence_blocks(self) -> None:
        result = evaluate(base_set(["A"]), [child("A", result_id="result-A")], aggregate(["A"]), result_records={("result-A", "1.0.0"): result_record("result-A", "B")})
        self.assertIn("RESULT_CHILD_MISMATCH", {finding.code for finding in result.findings})

    def test_result_digest_mismatch_blocks(self) -> None:
        result_ref = ref("result-A")
        result_ref["digest"] = "sha256:" + "f" * 64
        record = child("A", result_id="result-A")
        record["result_refs"] = [result_ref]
        result = evaluate(
            base_set(["A"]),
            [record],
            aggregate(["A"]),
            result_records={("result-A", "1.0.0"): result_record("result-A", "A")},
        )
        self.assertIn("RESULT_DIGEST_INVALID", {finding.code for finding in result.findings})

    def test_invalid_deadline_timestamp_blocks_without_raising(self) -> None:
        delegation = base_set(["A"])
        delegation["deadline"] = "not-a-timestamp"
        result = evaluate(
            delegation,
            [child("A", result_id="result-A")],
            aggregate(["A"]),
            as_of="2026-09-18T13:00:00Z",
            result_records={("result-A", "1.0.0"): result_record("result-A", "A")},
        )
        self.assertIn("DEADLINE_TIMESTAMP_INVALID", {finding.code for finding in result.findings})

    def test_malformed_objective_payload_blocks_without_raising(self) -> None:
        result = evaluate(
            base_set(["A"]),
            [child("A", result_id="result-A")],
            aggregate(["A"]),
            objective_payloads={"objective-1": {"goal": float("nan")}},
            result_records={("result-A", "1.0.0"): result_record("result-A", "A")},
        )
        self.assertIn("OBJECTIVE_DIGEST_INVALID", {finding.code for finding in result.findings})

    def test_successful_child_completed_after_deadline_blocks(self) -> None:
        record = child("A", result_id="result-A")
        record["completed_at"] = "2026-09-18T13:00:00Z"
        result = evaluate(
            base_set(["A"]),
            [record],
            aggregate(["A"]),
            as_of="2026-09-18T14:00:00Z",
            result_records={("result-A", "1.0.0"): result_record("result-A", "A")},
        )
        self.assertIn("DEADLINE_EXCEEDED", {finding.code for finding in result.findings})

    def test_result_binding_checks_delegation_and_status_when_present(self) -> None:
        result = evaluate(
            base_set(["A"]),
            [child("A", result_id="result-A")],
            aggregate(["A"]),
            result_records={
                ("result-A", "1.0.0"): {
                    **result_record("result-A", "A"),
                    "delegation_id": "other-delegation",
                    "status": "FAILED",
                }
            },
        )
        codes = {finding.code for finding in result.findings}
        self.assertIn("RESULT_DELEGATION_MISMATCH", codes)
        self.assertIn("RESULT_STATUS_MISMATCH", codes)

    def test_contradictory_results_block(self) -> None:
        record = child("A", result_id="result-A")
        record["result_refs"].append(ref("result-A-2"))
        results = {
            ("result-A", "1.0.0"): result_record("result-A", "A", outcome_digest="sha256:" + "1" * 64),
            ("result-A-2", "1.0.0"): result_record("result-A-2", "A", outcome_digest="sha256:" + "2" * 64),
        }
        result = evaluate(base_set(["A"]), [record], aggregate(["A"]), result_records=results)
        self.assertIn("CONTRADICTORY_RESULTS", {finding.code for finding in result.findings})

    def test_deadline_timeout_and_status_laundering_block(self) -> None:
        result = evaluate(base_set(["A"]), [child("A", status="TIMED_OUT")], aggregate(["A"]), as_of="2026-09-18T13:00:00Z", result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        codes = {finding.code for finding in result.findings}
        self.assertIn("DEADLINE_EXCEEDED", codes)
        self.assertIn("UNSAFE_CHILD_STATUS", codes)

    def test_provider_metadata_cannot_widen_scope(self) -> None:
        record = child("A", result_id="result-A")
        record["provider_metadata"] = {"authority_scope": "project-b", "capabilities": ["unlisted-capability"]}
        result = evaluate(base_set(["A"]), [record], aggregate(["A"]), objective_payloads={"objective-1": {"goal": "inspect"}}, available_capabilities={"capability-a"}, authority_scope_payloads=resolved_scopes(), as_of="2026-09-18T11:00:00Z", result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertEqual(result.status, "COMPLETE")
        self.assertEqual(result.findings, ())

    def test_declared_partial_aggregation_cannot_be_laundered(self) -> None:
        aggregation = aggregate(["A"])
        aggregation["aggregation_status"] = "PARTIAL"
        result = evaluate(
            base_set(["A"]),
            [child("A", result_id="result-A")],
            aggregation,
            objective_payloads={"objective-1": {"goal": "inspect"}},
            available_capabilities={"capability-a"},
            result_records={("result-A", "1.0.0"): result_record("result-A", "A")},
        )
        self.assertIn("AGGREGATION_STATUS_NOT_COMPLETE", {finding.code for finding in result.findings})

    def test_unresolved_required_inputs_block(self) -> None:
        result = evaluate(
            base_set(["A"]),
            [child("A", result_id="result-A")],
            aggregate(["A"]),
            result_records={("result-A", "1.0.0"): result_record("result-A", "A")},
        )
        codes = {finding.code for finding in result.findings}
        self.assertIn("OBJECTIVE_UNRESOLVED", codes)
        self.assertIn("CAPABILITIES_UNRESOLVED", codes)

    def test_missing_unexpected_and_included_children_block(self) -> None:
        missing = evaluate(base_set(["A", "B"]), [child("A", result_id="result-A")], aggregate(["A"]), result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertIn("MISSING_EXPECTED_CHILD", {finding.code for finding in missing.findings})
        unexpected = evaluate(base_set(["A"]), [child("A", result_id="result-A"), child("X", result_id="result-X")], aggregate(["A", "X"]), result_records={("result-A", "1.0.0"): result_record("result-A", "A"), ("result-X", "1.0.0"): result_record("result-X", "X")})
        self.assertIn("UNEXPECTED_CHILD", {finding.code for finding in unexpected.findings})
        invalid = evaluate(base_set(["A"]), [child("A", result_id="result-A")], aggregate(["A", "B"]), result_records={("result-A", "1.0.0"): result_record("result-A", "A")})
        self.assertIn("INCLUDED_NOT_OBSERVED", {finding.code for finding in invalid.findings})


if __name__ == "__main__":
    unittest.main()
