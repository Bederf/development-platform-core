import tempfile
import threading
import unittest
from pathlib import Path

from adapters.agent_runtime import AgentExecutionIdentity
from adapters.dsh_runtime import DshAgentRuntimeAdapter, DshRuntimeAdapter, DshRuntimeError


FAKE_DSH = """#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
home = pathlib.Path(os.environ['DSH_HOME'])
target = home / 'sessions' / 'attempt' / 'session-fake' / 'session.jsonl.zstd'
target.parent.mkdir(parents=True)
plain = target.with_suffix('')
plain.write_bytes((json.dumps({'type': 'session', 'id': 'dsh-session-fake'}) + '\\n').encode())
subprocess.run(['zstd', '-q', '-f', '-o', str(target), str(plain)], check=True)
plain.unlink()
sys.exit(int(os.environ.get('FAKE_DSH_EXIT', '0')))
"""


class DshRuntimeAdapterTests(unittest.TestCase):
    def identity(self, attempt: str = "attempt-1") -> AgentExecutionIdentity:
        return AgentExecutionIdentity("cp-1", "work-1", "run-1", f"execution-{attempt}", attempt)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.runtime_root = root / "runtime"
        self.runtime_root.mkdir()
        self.executable = root / "dsh"
        self.executable.write_text(FAKE_DSH)
        self.executable.chmod(0o700)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def adapter(self, credentials=None) -> DshRuntimeAdapter:
        return DshRuntimeAdapter(
            runtime_root=self.runtime_root,
            executable=self.executable,
            credential_resolver=lambda: credentials or {"DEEPSEEK_API_KEY": "test-only"},
        )

    def test_attempt_uses_disposable_home_and_records_provider_session(self) -> None:
        record = self.adapter().execute(self.identity(), args=(), cwd=self.runtime_root, model="test-model")

        self.assertEqual(record.provider_session_id, "dsh-session-fake")
        self.assertEqual(record.model, "test-model")
        self.assertEqual(record.identity.attempt_id, "attempt-1")
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(list(self.runtime_root.iterdir()), [])

    def test_retry_gets_a_new_disposable_home(self) -> None:
        first = self.adapter().execute(self.identity("attempt-1"), args=(), cwd=self.runtime_root)
        second = self.adapter().execute(self.identity("attempt-2"), args=(), cwd=self.runtime_root)

        self.assertEqual(first.provider_session_id, second.provider_session_id)
        self.assertNotEqual(first.identity.attempt_id, second.identity.attempt_id)
        self.assertEqual(list(self.runtime_root.iterdir()), [])

    def test_credential_scope_is_exact_and_not_recorded(self) -> None:
        with self.assertRaises(DshRuntimeError):
            self.adapter({"DEEPSEEK_API_KEY": "secret", "OTHER_SECRET": "no"}).execute(
                self.identity(), args=(), cwd=self.runtime_root,
            )

        record = self.adapter().execute(self.identity(), args=(), cwd=self.runtime_root)
        self.assertNotIn("DEEPSEEK_API_KEY", record.__dict__)
        self.assertNotIn("test-only", repr(record))

    def test_nonzero_exit_is_typed_execution_failure(self) -> None:
        self.executable.write_text(FAKE_DSH.replace("sys.exit(int(os.environ.get('FAKE_DSH_EXIT', '0')))", "sys.exit(7)"))
        record = self.adapter().execute(self.identity(), args=(), cwd=self.runtime_root)

        self.assertEqual(record.status, "failed")
        self.assertEqual(record.returncode, 7)

    def test_cancellation_terminates_process_and_removes_attempt_home(self) -> None:
        self.executable.write_text(FAKE_DSH.replace(
            "sys.exit(int(os.environ.get('FAKE_DSH_EXIT', '0')))",
            "import time; time.sleep(30)",
        ))
        cancelled = threading.Event()
        cancelled.set()

        record = self.adapter().execute(self.identity(), args=(), cwd=self.runtime_root, cancel_event=cancelled)

        self.assertEqual(record.status, "cancelled")
        self.assertNotEqual(record.returncode, 0)
        self.assertEqual(list(self.runtime_root.iterdir()), [])


class DshAgentRuntimeAdapterTests(unittest.TestCase):
    def identity(self, attempt: str = "attempt-1") -> dict:
        return {
            "control_plane_id": "cp-1",
            "work_item_id": "work-1",
            "run_id": "run-1",
            "execution_id": f"execution-{attempt}",
            "attempt_id": attempt,
        }

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.runtime_root = root / "runtime"
        self.runtime_root.mkdir()
        self.executable = root / "dsh"
        self.executable.write_text(FAKE_DSH)
        self.executable.chmod(0o700)
        runtime = DshRuntimeAdapter(
            runtime_root=self.runtime_root,
            executable=self.executable,
            credential_resolver=lambda: {
                "DEEPSEEK_API_KEY": "deepseek-test-only",
                "OPENAI_API_KEY": "openai-test-only",
            },
            allowed_credentials=("DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
        )
        self.adapter = DshAgentRuntimeAdapter(
            runtime,
            command_builder=lambda objective, model: (objective, model["provider"], model["model"]),
            artifact_collector=lambda _cwd, _identity, _record: ({
                "artifact_id": "artifact-1",
                "kind": "task-result",
                "uri": "memory://artifact-1",
                "digest": None,
                "producer": "dsh",
            },),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def request(self, operation: str, *, attempt: str = "attempt-1", **fields: object) -> dict:
        request = {
            "schema": "agent-runtime.v1",
            "message_type": "request",
            "operation": operation,
            "request_id": f"request-{operation}-{attempt}",
            "execution": self.identity(attempt),
        }
        request.update(fields)
        return request

    def test_success_maps_lifecycle_session_artifact_and_correlation(self) -> None:
        observed = []
        result = self.adapter.handle(
            self.request(
                "execute",
                task={"objective": "fake task"},
                model={"provider": "openai", "model": "gpt-test"},
            ),
            cwd=self.runtime_root,
            result_sink=observed.append,
        )

        self.assertEqual([item["status"] for item in observed], ["RUNNING", "SUCCEEDED"])
        self.assertEqual(result["in_reply_to"], "request-execute-attempt-1")
        self.assertEqual(result["execution"]["attempt_id"], "attempt-1")
        self.assertEqual(result["provider_session"]["session_id"], "dsh-session-fake")
        self.assertEqual(result["selected_model"], {"provider": "openai", "model": "gpt-test"})
        self.assertEqual(result["artifacts"][0]["publication"], "PRODUCED")
        self.assertNotIn("OPENAI_API_KEY", repr(result))
        self.assertNotIn("openai-test-only", repr(result))

    def test_model_selection_is_applied_to_execution(self) -> None:
        selected = self.adapter.handle(
            self.request("select_model", model={"provider": "openai", "model": "gpt-test"}),
            cwd=self.runtime_root,
        )
        result = self.adapter.handle(
            self.request("execute", task={"objective": "selected model task"}),
            cwd=self.runtime_root,
        )

        self.assertEqual(selected["selected_model"]["model"], "gpt-test")
        self.assertEqual(result["selected_model"]["provider"], "openai")

    def test_retry_preserves_parent_and_new_platform_attempt_identity(self) -> None:
        result = self.adapter.handle(
            self.request("retry", attempt="attempt-2", previous_attempt_id="attempt-1"),
            cwd=self.runtime_root,
        )

        self.assertEqual(result["retry"], {"parent_attempt_id": "attempt-1", "new_attempt_id": "attempt-2"})
        self.assertEqual(result["execution"]["attempt_id"], "attempt-2")

    def test_cancellation_reports_requested_then_completed(self) -> None:
        self.executable.write_text(FAKE_DSH.replace(
            "sys.exit(int(os.environ.get('FAKE_DSH_EXIT', '0')))",
            "import time; time.sleep(30)",
        ))
        request = self.request("execute", task={"objective": "long task"})
        result_holder = []
        worker = threading.Thread(target=lambda: result_holder.append(
            self.adapter.handle(request, cwd=self.runtime_root),
        ))
        worker.start()
        for _ in range(100):
            if "attempt-1" in self.adapter._cancellations:
                break
            threading.Event().wait(0.01)
        requested = self.adapter.handle(
            self.request("cancel", reason="operator requested cancellation"),
            cwd=self.runtime_root,
        )
        worker.join(timeout=5)

        self.assertEqual(requested["status"], "CANCEL_REQUESTED")
        self.assertTrue(result_holder)
        self.assertEqual(result_holder[0]["status"], "CANCELLED")
        self.assertEqual(result_holder[0]["events"][0]["event_type"], "execution_cancelled")
        self.assertTrue(result_holder[0]["cancellation"]["completed"])

    def test_invalid_contract_request_fails_closed(self) -> None:
        with self.assertRaises(DshRuntimeError):
            self.adapter.handle({
                "schema": "agent-runtime.v1",
                "message_type": "result",
                "operation": "execute",
                "request_id": "invalid",
                "execution": self.identity(),
            }, cwd=self.runtime_root)


if __name__ == "__main__":
    unittest.main()
