"""Normalize provider check observations into ``verification-result.v1``."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping


class VerificationResultError(ValueError):
    """Raised when a provider result cannot be mapped fail-closed."""


class VerificationResultAdapter:
    """Convert bounded provider check output without granting acceptance."""

    def normalize(
        self,
        *,
        request_id: str,
        provider_status: str,
        checks: Iterable[Mapping[str, Any]],
        evidence: Iterable[str] = (),
    ) -> dict[str, Any]:
        if not isinstance(request_id, str) or not request_id.strip():
            raise VerificationResultError("request_id must be a non-empty string")
        if provider_status not in {
            "PASS",
            "FAIL",
            "INCOMPLETE",
            "NOT_RUN",
            "CANCELLED",
            "INTERRUPTED",
            "TIMEOUT",
            "PARTIAL",
        }:
            raise VerificationResultError(f"unsupported provider status: {provider_status!r}")

        normalized: list[dict[str, Any]] = []
        for raw in checks:
            if not isinstance(raw, Mapping):
                raise VerificationResultError("each check must be an object")
            check_id = raw.get("check_id", raw.get("name"))
            if not isinstance(check_id, str) or not check_id.strip():
                raise VerificationResultError("each check requires a non-empty check_id or name")
            status = self._check_status(raw)
            normalized.append(
                {
                    "check_id": check_id,
                    "status": status,
                    "command": self._optional_string(raw.get("command")),
                    "evidence_ref": self._optional_string(raw.get("evidence_ref")),
                }
            )

        if provider_status in {"CANCELLED", "INTERRUPTED", "TIMEOUT", "PARTIAL", "INCOMPLETE"}:
            # verification-result.v1 has one non-positive representation for
            # an operation whose complete result is unavailable. Detailed
            # cancellation/timeout/partial semantics belong to evaluation.v1.
            status = "INCOMPLETE"
        elif any(check["status"] == "FAILED" for check in normalized):
            status = "FAILED"
        elif provider_status == "PASS" and normalized and all(check["status"] == "PASSED" for check in normalized):
            status = "PASSED"
        elif provider_status == "FAIL":
            status = "FAILED"
        elif provider_status == "INCOMPLETE":
            status = "INCOMPLETE"
        else:
            status = "NOT_RUN"

        return {
            "schema": "verification-result.v1",
            "request_id": request_id,
            "status": status,
            "checks": normalized,
            "evidence": list(deepcopy(list(evidence))),
        }

    @staticmethod
    def _check_status(raw: Mapping[str, Any]) -> str:
        declared = raw.get("status")
        if declared in {"PASSED", "FAILED", "SKIPPED"}:
            return str(declared)
        if declared in {"PASS", "FAIL", "SKIP"}:
            return {"PASS": "PASSED", "FAIL": "FAILED", "SKIP": "SKIPPED"}[str(declared)]
        exit_code = raw.get("exit_code")
        if isinstance(exit_code, int):
            return "PASSED" if exit_code == 0 else "FAILED"
        if raw.get("skipped") is True:
            return "SKIPPED"
        raise VerificationResultError("check requires status, exit_code, or skipped=true")

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise VerificationResultError("command and evidence_ref must be strings or null")
        return value
