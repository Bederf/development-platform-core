"""Exploratory RTK-like command-output projection fixtures.

Raw execution remains authoritative; the adapter only creates a bounded,
reversible view for the model.
"""

from __future__ import annotations

import hashlib
import unittest


class FakeTerminalProjector:
    def __init__(self) -> None:
        self.raw: dict[str, str] = {}

    def project(self, execution_id: str, output: str, *, exit_code: int, limit: int = 240) -> dict:
        raw_digest = hashlib.sha256(output.encode()).hexdigest()
        self.raw[execution_id] = output
        lines = output.splitlines()
        useful = [line for line in lines if any(token in line.lower() for token in ("fail", "error", "traceback"))]
        summary = "\n".join([f"exit_code={exit_code}", *useful[:8]])
        return {
            "execution_id": execution_id,
            "projection": summary[:limit],
            "raw_digest": raw_digest,
            "raw_ref": f"raw:{execution_id}:{raw_digest}",
            "exit_code": exit_code,
            "authoritative": False,
        }

    def retrieve(self, raw_ref: str) -> str:
        _, execution_id, _ = raw_ref.split(":", 2)
        return self.raw[execution_id]


class CommandContextProjectionConformanceTests(unittest.TestCase):
    def test_projection_preserves_exit_status_and_failure_identity(self) -> None:
        output = "37 passed\n2 failed\nFAILED tests/test_auth.py::test_login\n"
        result = FakeTerminalProjector().project("exec-1", output, exit_code=1)
        self.assertIn("exit_code=1", result["projection"])
        self.assertIn("2 failed", result["projection"])
        self.assertIn("test_auth.py::test_login", result["projection"])

    def test_projection_is_smaller_but_raw_output_is_recoverable(self) -> None:
        output = "noise\n" * 500 + "Traceback (most recent call last):\nAssertionError\n"
        projector = FakeTerminalProjector()
        result = projector.project("exec-2", output, exit_code=1, limit=120)
        self.assertLess(len(result["projection"]), len(output))
        self.assertEqual(projector.retrieve(result["raw_ref"]), output)
        self.assertEqual(result["raw_digest"], hashlib.sha256(output.encode()).hexdigest())

    def test_successful_output_keeps_exit_zero(self) -> None:
        result = FakeTerminalProjector().project("exec-3", "12 passed\n", exit_code=0)
        self.assertIn("exit_code=0", result["projection"])
        self.assertEqual(result["exit_code"], 0)

    def test_projection_never_becomes_evidence_or_verification(self) -> None:
        result = FakeTerminalProjector().project("exec-4", "1 passed\n", exit_code=0)
        self.assertFalse(result["authoritative"])
        self.assertNotIn("verification_status", result)
        self.assertNotIn("evidence_status", result)

    def test_raw_digest_changes_when_output_changes(self) -> None:
        projector = FakeTerminalProjector()
        first = projector.project("exec-5", "old output\n", exit_code=0)
        second = projector.project("exec-5", "new output\n", exit_code=0)
        self.assertNotEqual(first["raw_digest"], second["raw_digest"])

    def test_tampered_reference_cannot_retrieve_another_execution(self) -> None:
        projector = FakeTerminalProjector()
        result = projector.project("exec-6", "output\n", exit_code=0)
        with self.assertRaises(KeyError):
            projector.retrieve(result["raw_ref"].replace("exec-6", "exec-unknown"))

    def test_limit_bounds_model_projection_only(self) -> None:
        output = "error: critical failure\n" + ("detail\n" * 100)
        projector = FakeTerminalProjector()
        result = projector.project("exec-7", output, exit_code=2, limit=40)
        self.assertLessEqual(len(result["projection"]), 40)
        self.assertEqual(projector.retrieve(result["raw_ref"]), output)


if __name__ == "__main__":
    unittest.main()
