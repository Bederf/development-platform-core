import unittest

from adapters.gateway_compatibility import ProjectionError, project_execution_request, project_policy_decision


class GatewayCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.request = {"request_id": "r1", "session_id": "s1", "task_id": "t1", "capability": "read", "arguments": {"path": "src"}, "arguments_sha256": "sha256:a", "authorization_id": "d1", "timeout_seconds": 30, "target": {"id": "repo"}, "baseline": {"id": "base"}, "capability_binding": {"id": "binding"}}
        self.decision = {"decision_id": "d1", "decision": "allow", "policy_id": "p", "policy_version": "1", "issued_at": "2026-01-01T00:00:00Z", "expires_at": "2027-01-01T00:00:00Z", "decision_digest": "sha256:d", "authority_binding": {"id": "authority"}}

    def test_projection_is_non_authoritative(self):
        policy = project_policy_decision(self.request, self.decision)
        execution = project_execution_request(self.request, policy)
        self.assertFalse(policy["authoritative"])
        self.assertFalse(execution["authoritative"])

    def test_missing_digest_fails_closed(self):
        decision = dict(self.decision)
        del decision["decision_digest"]
        with self.assertRaisesRegex(ProjectionError, "decision_digest"):
            project_policy_decision(self.request, decision)

    def test_deny_cannot_project(self):
        decision = dict(self.decision, decision="deny")
        with self.assertRaises(ProjectionError):
            project_policy_decision(self.request, decision)

    def test_missing_execution_semantics_fails_closed(self):
        policy = project_policy_decision(self.request, self.decision)
        request = dict(self.request)
        del request["baseline"]
        with self.assertRaisesRegex(ProjectionError, "baseline"):
            project_execution_request(request, policy)

    def test_wrong_authorization_identity_fails(self):
        policy = project_policy_decision(self.request, self.decision)
        with self.assertRaisesRegex(ProjectionError, "identity"):
            project_execution_request(dict(self.request, authorization_id="other"), policy)

    def test_missing_authority_fails(self):
        with self.assertRaisesRegex(ProjectionError, "authority"):
            project_policy_decision(self.request, dict(self.decision, authority_binding=None))

    def test_missing_target_fails(self):
        policy = project_policy_decision(self.request, self.decision)
        request = dict(self.request); del request["target"]
        with self.assertRaisesRegex(ProjectionError, "target"):
            project_execution_request(request, policy)

    def test_review_required_fails(self):
        with self.assertRaises(ProjectionError):
            project_policy_decision(self.request, dict(self.decision, decision="review_required"))


if __name__ == "__main__":
    unittest.main()
