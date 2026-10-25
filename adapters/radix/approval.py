"""Semantic verification for attributable bootstrap approvals."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


class BootstrapApprovalError(ValueError):
    """Raised when an approval cannot authorize the referenced plan."""


def plan_digest(plan: Mapping[str, Any]) -> str:
    """Return the immutable digest used by the bootstrap approval subject."""

    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def verify_approval(*, plan: Mapping[str, Any], approval: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    """Verify an approved decision is attributable to this exact plan."""

    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(approval),
        key=lambda error: list(error.path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "document"
        raise BootstrapApprovalError(f"invalid bootstrap approval at {location}: {errors[0].message}")
    if approval["decision"] != "approved":
        raise BootstrapApprovalError("bootstrap approval decision is not approved")
    subject = approval["subject"]
    if subject["project_id"] != plan.get("project_id"):
        raise BootstrapApprovalError("bootstrap approval project_id does not match plan")
    if subject["id"] != plan.get("plan_id"):
        raise BootstrapApprovalError("bootstrap approval subject does not match plan")
    if subject["version"] != "1.0.0":
        raise BootstrapApprovalError("unsupported bootstrap plan version")
    if subject["digest"] != plan_digest(plan):
        raise BootstrapApprovalError("bootstrap approval digest does not match plan")
    valid_until = approval.get("valid_until")
    if valid_until is not None:
        expiry = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
        if expiry <= datetime.now(timezone.utc):
            raise BootstrapApprovalError("bootstrap approval is expired")
