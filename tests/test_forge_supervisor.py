from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event

from adapters.forge_supervisor import ForgeProcessSupervisor


class ForgeProcessSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.supervisor = ForgeProcessSupervisor()

    def command(self, seconds: float) -> list[str]:
        return [sys.executable, "-c", f"import time; time.sleep({seconds})"]

    def test_timeout_produces_non_success_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.supervisor.run(self.command(2), repository=Path(directory), timeout_seconds=0.05)
        self.assertEqual(result.provider_status, "TIMEOUT")
        self.assertEqual(result.termination_reason, "supervisor timeout")
        self.assertIsNotNone(result.termination_signal)

    def test_cancellation_produces_non_success_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cancelled = Event()
            cancelled.set()
            result = self.supervisor.run(
                self.command(2), repository=Path(directory), timeout_seconds=5, cancel_event=cancelled
            )
        self.assertEqual(result.provider_status, "CANCELLED")
        self.assertEqual(result.termination_reason, "operator cancellation")
        self.assertIsNotNone(result.termination_signal)

    def test_completed_process_preserves_provider_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.supervisor.run(
                [sys.executable, "-c", "print('complete')"], repository=Path(directory), timeout_seconds=5
            )
        self.assertEqual(result.provider_status, "PASS")
        self.assertEqual(result.returncode, 0)
        self.assertIn("complete", result.stdout)
        self.assertIsNone(result.termination_reason)


if __name__ == "__main__":
    unittest.main()
