import unittest

from adapters.gsd_evaluation import (
    compare_metrics,
    experimental_independence_is_proven,
    pattern_is_candidate_eligible,
)
from tests.test_contracts import validate


GUARDRAILS = {"correctness_preserved": True, "verification_preserved": True, "evidence_complete": True, "regressions_within_limit": True}


class GsdEvaluationTests(unittest.TestCase):
    def experiment_records(self):
        return [
            {"cohort": "baseline", "session_id": "s1", "execution_id": "e1", "fixture_id": "f1", "output_digest": "o1"},
            {"cohort": "candidate", "session_id": "s2", "execution_id": "e2", "fixture_id": "f2", "output_digest": "o2"},
        ]

    def test_candidate_can_win_only_when_all_metrics_improve(self):
        result = compare_metrics({"correctness": 1, "time": 10}, {"correctness": 1, "time": 8}, {"correctness": "higher_is_better", "time": "lower_is_better"}, guardrails=GUARDRAILS)
        self.assertEqual(result, "candidate_better")

    def test_failed_safety_guardrail_rejects_candidate(self):
        guardrails = dict(GUARDRAILS, verification_preserved=False)
        result = compare_metrics({"time": 10}, {"time": 1}, {"time": "lower_is_better"}, guardrails=guardrails)
        self.assertEqual(result, "rejected_by_guardrail")

    def test_mixed_metric_result_is_inconclusive(self):
        result = compare_metrics({"time": 10, "remediation": 1}, {"time": 8, "remediation": 2}, {"time": "lower_is_better", "remediation": "lower_is_better"}, guardrails=GUARDRAILS)
        self.assertEqual(result, "inconclusive")

    def test_evaluation_record_requires_held_out_evidence(self):
        record = {
            "schema": "gsd-evaluation.v1", "evaluation_id": "evaluation.001",
            "baseline": {"id": "gsd.3.3", "version": "3.3.0", "graph_version": "1.0.0", "profile": "medium"},
            "candidate": {"id": "gsd.3.4", "version": "3.4.0", "graph_version": "1.1.0", "profile": "medium"},
            "dataset": {"training_refs": [{"id": "session.001", "version": "1.0.0"}], "held_out_refs": [{"id": "session.002", "version": "1.0.0"}]},
            "metrics": [{"metric": "verification_pass_rate", "baseline": 0.8, "candidate": 0.9, "direction": "higher_is_better", "evidence": [{"id": "session.002", "version": "1.0.0"}]}],
            "guardrails": GUARDRAILS, "outcome": "candidate_better", "recorded_at": "2026-08-29T10:00:00Z",
        }
        validate("gsd-evaluation.v1.schema.json", record)

    def test_pattern_requires_strong_independent_evidence_for_promotion(self):
        proof = {"session_record_refs": [{"id": "session.001", "version": "1.0.0"}, {"id": "session.002", "version": "1.0.0"}, {"id": "session.003", "version": "1.0.0"}], "execution_ids": ["exec.001", "exec.002", "exec.003"], "lineage_checked": True, "attestation_ref": {"id": "attestation.001", "version": "1.0.0"}}
        pattern = {"confidence": "high", "strength": {"evidence_level": 3, "independent_session_count": 3, "reproducible": True, "candidate_eligible": True, "independence_proof": proof}}
        self.assertTrue(pattern_is_candidate_eligible(pattern))
        weak = {"confidence": "very_high", "strength": {"evidence_level": 3, "independent_session_count": 10, "reproducible": True, "candidate_eligible": True, "independence_proof": {"session_record_refs": proof["session_record_refs"], "execution_ids": ["exec.001", "exec.001", "exec.001"], "lineage_checked": True, "attestation_ref": proof["attestation_ref"]}}}
        self.assertFalse(pattern_is_candidate_eligible(weak))

    def test_experiment_requires_distinct_fixtures_and_outputs(self):
        self.assertTrue(experimental_independence_is_proven(self.experiment_records()))

    def test_shared_fixture_is_not_independent(self):
        records = self.experiment_records()
        records[1]["fixture_id"] = records[0]["fixture_id"]
        self.assertFalse(experimental_independence_is_proven(records))

    def test_cross_cohort_session_or_execution_is_not_independent(self):
        records = self.experiment_records()
        records[1]["session_id"] = records[0]["session_id"]
        self.assertFalse(experimental_independence_is_proven(records))

    def test_copied_output_is_not_independent(self):
        records = self.experiment_records()
        records[1]["output_digest"] = records[0]["output_digest"]
        self.assertFalse(experimental_independence_is_proven(records))


if __name__ == "__main__":
    unittest.main()
