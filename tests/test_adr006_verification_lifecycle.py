"""Conformance tests for ADR-006 GSD–Forge verification lifecycle."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from adapters.verification_lifecycle import (
    DuplicateVerificationAttempt,
    ForgeResult,
    ImmutableAttemptError,
    ProcessIdentity,
    RecoveryDenied,
    VerificationLifecycle,
    VerificationLifecycleError,
)


class ADR006VerificationLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.lifecycle = VerificationLifecycle(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def attempt(self, *, repository: str = "repo", baseline: str = "rev-1", **kwargs):
        attempt = self.lifecycle.create_attempt(
            gsd_session_id=kwargs.get("gsd_session_id", "gsd-1"),
            forge_session_id=kwargs.get("forge_session_id", "forge-1"),
            execution_id=kwargs.get("execution_id", "exec-1"),
            attempt_id=kwargs.get("attempt_id"),
            verification_attempt_id=kwargs.get("verification_attempt_id"),
            repository=repository,
            baseline=baseline,
            lineage=kwargs.get("lineage", ("root",)),
        )
        self.lifecycle.transition(attempt.identity.verification_attempt_id, "VERIFICATION_PENDING", "verification_requested")
        return self.lifecycle.transition(
            attempt.identity.verification_attempt_id, "FORGE_RUNNING", "forge_launch_accepted"
        )

    @staticmethod
    def result(attempt, status: str = "PASS", **changes) -> ForgeResult:
        identity = attempt.identity
        values = {
            "verification_attempt_id": identity.verification_attempt_id,
            "gsd_session_id": identity.gsd_session_id,
            "forge_session_id": identity.forge_session_id,
            "execution_id": identity.execution_id,
            "attempt_id": identity.attempt_id,
            "repository": identity.repository,
            "baseline": identity.baseline,
            "lineage": identity.lineage,
        }
        values.update(changes)
        return ForgeResult(status=status, evidence={"bound": True}, **values)

    def test_agent_exit_zero_cannot_complete_without_forge_pass(self) -> None:
        attempt = self.attempt()
        self.assertNotEqual(attempt.state, "DONE")
        self.assertEqual(self.lifecycle.store.load(attempt.identity.verification_attempt_id).state, "FORGE_RUNNING")

    def test_timeout_cannot_become_pass(self) -> None:
        attempt = self.attempt()
        timed_out = self.lifecycle.timeout(attempt.identity.verification_attempt_id)
        self.assertEqual(timed_out.state, "VERIFICATION_TIMEOUT")
        updated, accepted = self.lifecycle.apply_result(self.result(timed_out))
        self.assertFalse(accepted)
        self.assertEqual(updated.state, "VERIFICATION_TIMEOUT")

    def test_interrupted_forge_cannot_become_pass(self) -> None:
        attempt = self.attempt()
        interrupted = self.lifecycle.interrupt(attempt.identity.verification_attempt_id)
        self.assertEqual(interrupted.state, "VERIFICATION_INTERRUPTED")
        updated, accepted = self.lifecycle.apply_result(self.result(interrupted))
        self.assertFalse(accepted)
        self.assertEqual(updated.state, "VERIFICATION_INTERRUPTED")

    def test_stale_attempt_one_pass_cannot_close_attempt_two(self) -> None:
        first = self.attempt()
        self.lifecycle.timeout(first.identity.verification_attempt_id)
        second = self.attempt(verification_attempt_id="vat-2", attempt_id="attempt-2")
        updated, accepted = self.lifecycle.apply_result(self.result(first))
        self.assertFalse(accepted)
        self.assertEqual(updated.state, "VERIFICATION_TIMEOUT")
        self.assertEqual(self.lifecycle.store.load(second.identity.verification_attempt_id).state, "FORGE_RUNNING")

    def test_duplicate_attempts_cannot_overwrite_lineage(self) -> None:
        self.attempt()
        with self.assertRaises(DuplicateVerificationAttempt):
            self.attempt(verification_attempt_id="vat-2", attempt_id="attempt-2")

    def test_terminal_attempt_id_cannot_be_reused(self) -> None:
        first = self.attempt()
        self.lifecycle.timeout(first.identity.verification_attempt_id)
        with self.assertRaises(ImmutableAttemptError):
            self.attempt(verification_attempt_id=first.identity.verification_attempt_id, attempt_id="retry")

    def test_late_pass_after_timeout_cannot_resurrect_attempt(self) -> None:
        attempt = self.attempt()
        timed_out = self.lifecycle.timeout(attempt.identity.verification_attempt_id)
        updated, accepted = self.lifecycle.apply_result(self.result(timed_out))
        self.assertFalse(accepted)
        self.assertEqual(updated.state, "VERIFICATION_TIMEOUT")

    def test_restart_preserves_immutable_attempt_identity(self) -> None:
        attempt = self.attempt()
        restarted = VerificationLifecycle(Path(self.temp.name))
        loaded = restarted.store.load(attempt.identity.verification_attempt_id)
        self.assertEqual(loaded.identity, attempt.identity)
        self.assertEqual(loaded.state, "FORGE_RUNNING")

    def test_orphaned_forge_session_cannot_authorize_completion(self) -> None:
        attempt = self.attempt()
        reconciled = self.lifecycle.reconcile_restart(attempt.identity.verification_attempt_id, "active")
        self.assertEqual(reconciled.state, "VERIFICATION_UNKNOWN")
        updated, accepted = self.lifecycle.apply_result(self.result(reconciled))
        self.assertFalse(accepted)
        self.assertEqual(updated.state, "VERIFICATION_UNKNOWN")

    def test_manual_recovery_cannot_manufacture_pass(self) -> None:
        attempt = self.attempt()
        with self.assertRaises(RecoveryDenied):
            self.lifecycle.manual_recover(attempt.identity.verification_attempt_id, "new_attempt")
        self.assertNotEqual(self.lifecycle.store.load(attempt.identity.verification_attempt_id).state, "DONE")

    def test_unrelated_process_cannot_be_killed(self) -> None:
        expected = ProcessIdentity(41, 41, 41, "start-1", "/bin/forge", "forge finish", "vat-1")
        unrelated = replace(expected, pid=42, start_time="start-2")
        self.assertFalse(self.lifecycle.owns_process(expected, unrelated))
        signals: list[int] = []
        self.assertFalse(self.lifecycle.cleanup_owned_process(expected, unrelated, signals.append))
        self.assertEqual(signals, [])
        self.assertTrue(self.lifecycle.cleanup_owned_process(expected, expected, signals.append))
        self.assertEqual(signals, [41])

    def test_failed_differs_from_verification_failed(self) -> None:
        execution_failure = self.lifecycle.create_attempt(
            gsd_session_id="gsd-fail", forge_session_id="forge-fail", execution_id="exec-fail",
            repository="repo-fail", baseline="rev-1", lineage=("root",),
        )
        execution_failure = self.lifecycle.transition(
            execution_failure.identity.verification_attempt_id, "FAILED", "agent_execution_failed"
        )
        self.assertEqual(execution_failure.state, "FAILED")

        verification_failure = self.attempt(repository="repo-verify")
        failed, accepted = self.lifecycle.apply_result(self.result(verification_failure, status="FAIL"))
        self.assertTrue(accepted)
        self.assertEqual(failed.state, "VERIFICATION_FAILED")
        self.assertNotEqual(execution_failure.state, failed.state)

    def test_missing_or_corrupt_forge_state_is_unknown(self) -> None:
        attempt = self.attempt()
        path = Path(self.temp.name) / f"{attempt.identity.verification_attempt_id}.json"
        path.write_text("{not-json", encoding="utf-8")
        with self.assertRaises(VerificationLifecycleError):
            VerificationLifecycle(self.temp.name).store.load(attempt.identity.verification_attempt_id)


if __name__ == "__main__":
    unittest.main()
