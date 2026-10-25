from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from adapters.verification_result import VerificationResultAdapter, VerificationResultError


ROOT = Path(__file__).parents[1]


class VerificationResultAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = VerificationResultAdapter()
        schema = json.loads((ROOT / "contracts/verification-result.v1.schema.json").read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema)

    def test_normalizes_forge_style_checks_to_schema(self) -> None:
        result = self.adapter.normalize(
            request_id="verify-request-001",
            provider_status="PASS",
            checks=({"name": "unit-tests", "exit_code": 0, "command": "pytest"},),
            evidence=("forge://observation/001",),
        )
        self.validator.validate(result)
        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["checks"][0]["check_id"], "unit-tests")

    def test_failed_check_overrides_claimed_provider_pass(self) -> None:
        result = self.adapter.normalize(
            request_id="verify-request-002",
            provider_status="PASS",
            checks=({"name": "unit-tests", "exit_code": 1},),
        )
        self.assertEqual(result["status"], "FAILED")
        self.validator.validate(result)

    def test_empty_claimed_pass_is_not_satisfied(self) -> None:
        result = self.adapter.normalize(request_id="verify-request-003", provider_status="PASS", checks=())
        self.assertEqual(result["status"], "NOT_RUN")
        self.validator.validate(result)

    def test_interrupted_provider_result_is_incomplete_even_with_partial_passes(self) -> None:
        result = self.adapter.normalize(
            request_id="verify-request-interrupted",
            provider_status="INTERRUPTED",
            checks=({"name": "startup", "exit_code": 0},),
        )
        self.assertEqual(result["status"], "INCOMPLETE")
        self.validator.validate(result)

    def test_timeout_and_cancellation_are_incomplete_legacy_results(self) -> None:
        for provider_status in ("TIMEOUT", "CANCELLED", "PARTIAL"):
            with self.subTest(provider_status=provider_status):
                result = self.adapter.normalize(
                    request_id=f"verify-request-{provider_status.lower()}",
                    provider_status=provider_status,
                    checks=(),
                )
                self.assertEqual(result["status"], "INCOMPLETE")
                self.validator.validate(result)

    def test_rejects_unmappable_check_and_status(self) -> None:
        with self.assertRaises(VerificationResultError):
            self.adapter.normalize(request_id="verify-request-004", provider_status="MAYBE", checks=())
        with self.assertRaises(VerificationResultError):
            self.adapter.normalize(request_id="verify-request-005", provider_status="PASS", checks=({"name": "bad"},))


if __name__ == "__main__":
    unittest.main()
