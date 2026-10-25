import unittest

from adapters.agent_runtime import AgentExecutionIdentity, AgentRuntimeIdentityBridge, AgentRuntimeIdentityError


class AgentRuntimeIdentityBridgeTests(unittest.TestCase):
    def identity(self) -> AgentExecutionIdentity:
        return AgentExecutionIdentity("cp-1", "work-1", "run-1", "execution-1", "attempt-1")

    def test_provider_session_is_child_observation_of_platform_identity(self) -> None:
        bridge = AgentRuntimeIdentityBridge(self.identity(), provider="dsh")
        bridge.bind_session("dsh-session-1")

        projected = bridge.project_context({"current_objective": "authoritative task"})

        self.assertEqual(projected["current_objective"], "authoritative task")
        self.assertEqual(projected["agent_runtime"]["attempt_id"], "attempt-1")
        self.assertEqual(projected["agent_runtime"]["provider_session_id"], "dsh-session-1")

    def test_provider_cannot_replace_platform_session_identity(self) -> None:
        bridge = AgentRuntimeIdentityBridge(self.identity(), provider="dsh")
        bridge.bind_session("dsh-session-1")

        with self.assertRaises(AgentRuntimeIdentityError):
            bridge.bind_session("dsh-session-2")

    def test_retry_uses_a_new_bridge_and_preserves_first_identity(self) -> None:
        first = AgentRuntimeIdentityBridge(self.identity(), provider="dsh")
        first.bind_session("dsh-session-a")
        second = AgentRuntimeIdentityBridge(
            AgentExecutionIdentity("cp-1", "work-1", "run-1", "execution-2", "attempt-2"),
            provider="dsh",
        )
        second.bind_session("dsh-session-b")

        self.assertNotEqual(first.identity.attempt_id, second.identity.attempt_id)
        self.assertNotEqual(first.session.session_id, second.session.session_id)
        self.assertEqual(first.identity.execution_id, "execution-1")

    def test_identity_fields_are_required(self) -> None:
        with self.assertRaises(AgentRuntimeIdentityError):
            AgentExecutionIdentity("cp-1", "", "run-1", "execution-1", "attempt-1")


if __name__ == "__main__":
    unittest.main()
