import unittest

from tests.test_contracts import validate


class GsdLearningContractTests(unittest.TestCase):
    def test_evidence_observation_pattern_and_candidates(self):
        observation = {"schema": "gsd-learning.v1", "id": "observation.001", "version": "1.0.0", "entity_type": "observation", "statement": "Verification failures cluster after integration.", "evidence": [{"id": "session.001", "version": "1.0.0"}], "confidence": "high", "observed_at": "2026-08-29T10:00:00Z", "session_refs": [{"id": "session.001", "version": "1.0.0"}]}
        validate("gsd-learning.v1.schema.json", observation)
        pattern = dict(observation, id="pattern.001", entity_type="pattern", observation_refs=[{"id": "observation.001", "version": "1.0.0"}, {"id": "observation.002", "version": "1.0.0"}], scope="medium-profile runs", strength={"evidence_level": 2, "independent_session_count": 2, "reproducible": False, "candidate_eligible": False, "independence_proof": {"session_record_refs": [{"id": "session.001", "version": "1.0.0"}, {"id": "session.002", "version": "1.0.0"}, {"id": "session.003", "version": "1.0.0"}], "execution_ids": ["exec.001", "exec.002", "exec.003"], "lineage_checked": True, "attestation_ref": {"id": "attestation.001", "version": "1.0.0"}}})
        pattern.pop("session_refs")
        validate("gsd-learning.v1.schema.json", pattern)
        candidate = {"schema": "gsd-learning.v1", "id": "candidate.001", "version": "1.0.0", "entity_type": "procedural_candidate", "observation_refs": [{"id": "observation.001", "version": "1.0.0"}], "pattern_refs": [], "proposed_change": "Reuse the existing dependency-state check.", "provenance": [{"id": "session.001", "version": "1.0.0"}], "status": "proposed", "created_at": "2026-08-29T10:00:00Z", "affected_capability": {"id": "dependency-governance", "version": "1.0.0"}}
        validate("gsd-learning.v1.schema.json", candidate)

    def test_process_candidate_decision_and_adoption_are_linked(self):
        candidate = {"schema": "gsd-learning.v1", "id": "candidate.002", "version": "1.0.0", "entity_type": "process_candidate", "observation_refs": [{"id": "observation.001", "version": "1.0.0"}], "pattern_refs": [], "proposed_change": "Add an evidence gate before integration.", "provenance": [{"id": "session.001", "version": "1.0.0"}], "status": "proposed", "created_at": "2026-08-29T10:00:00Z", "affected_graph": {"id": "gsd.graph", "version": "1.0.0"}, "affected_profile": "medium"}
        validate("gsd-learning.v1.schema.json", candidate)
        decision = {"schema": "gsd-learning.v1", "id": "decision.001", "version": "1.0.0", "entity_type": "governance_decision", "candidate": {"id": "candidate.002", "version": "1.0.0"}, "decision": "approve", "authority": {"id": "governance.001", "version": "1.0.0"}, "rationale": "Evidence supports the bounded change.", "decided_at": "2026-08-29T10:00:00Z"}
        validate("gsd-learning.v1.schema.json", decision)
        adoption = {"schema": "gsd-learning.v1", "id": "adoption.001", "version": "1.0.0", "entity_type": "adoption_evidence", "candidate": {"id": "candidate.002", "version": "1.0.0"}, "decision": {"id": "decision.001", "version": "1.0.0"}, "compatibility_check": {"id": "compatibility.001", "version": "1.0.0"}, "adopted_version": "1.1.0", "evidence": [{"id": "verification.001", "version": "1.0.0"}], "recorded_at": "2026-08-29T10:00:00Z"}
        validate("gsd-learning.v1.schema.json", adoption)

    def test_model_update_is_not_a_learning_artifact(self):
        with self.assertRaises(Exception):
            validate("gsd-learning.v1.schema.json", {"schema": "gsd-learning.v1", "id": "bad", "version": "1.0.0", "entity_type": "model_update"})
