"""Journal-backed operation identity primitives for GSD P045 T001.

This module owns only canonical operation/input identity and duplicate or
conflict classification. It does not dispatch work, create workspaces, or
change task/attempt state.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from .gsd_execution_journal import JournalError, JournalEvent, JournalStore


class OperationIdentityError(ValueError):
    """Raised when an operation identity cannot be admitted safely."""


_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def input_digest(value: Any) -> str:
    """Return the canonical digest of an operation input value."""

    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OperationIdentityError("operation input is not canonically serializable") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OperationIdentity:
    operation_id: str
    input_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise OperationIdentityError("operation identity requires a non-empty operation_id")
        if not isinstance(self.input_digest, str) or not _SHA256_DIGEST.fullmatch(self.input_digest):
            raise OperationIdentityError("operation identity requires a canonical SHA-256 input digest")

    @classmethod
    def from_input(cls, operation_id: str, value: Any) -> "OperationIdentity":
        if not isinstance(operation_id, str) or not operation_id:
            raise OperationIdentityError("operation identity requires a non-empty operation_id")
        return cls(operation_id, input_digest(value))


@dataclass(frozen=True)
class OperationDecision:
    identity: OperationIdentity
    attempt_id: str
    decision: str
    sequence: int


class OperationIdentityRegistry:
    """Commit one operation decision and fail closed on identity conflicts."""

    def __init__(self, journal: JournalStore, *, controller_epoch: int = 1):
        if controller_epoch < 1:
            raise OperationIdentityError("controller epoch must be positive")
        self.journal = journal
        self.controller_epoch = controller_epoch

    def register(
        self,
        identity: OperationIdentity,
        *,
        attempt_id: str,
    ) -> OperationDecision:
        if not isinstance(attempt_id, str) or not attempt_id:
            raise OperationIdentityError("operation decision requires a non-empty attempt_id")
        existing = self._find(identity.operation_id)
        if existing is not None:
            if existing.identity.input_digest != identity.input_digest:
                raise OperationIdentityError(
                    "operation identity conflict: input digest differs for existing operation"
                )
            return existing

        event = JournalEvent(
            event_id=f"operation-identity:{identity.operation_id}",
            event_type="OUTCOME",
            controller_epoch=self.controller_epoch,
            operation_id=identity.operation_id,
            payload={
                "kind": "OPERATION_DECISION",
                "operation_id": identity.operation_id,
                "input_digest": identity.input_digest,
                "attempt_id": attempt_id,
                "decision": "ACCEPTED",
            },
        )
        try:
            committed = self.journal.append(event)
        except JournalError as exc:
            raise OperationIdentityError("operation identity decision could not be committed") from exc
        return OperationDecision(identity, attempt_id, "ACCEPTED", committed.sequence or 0)

    def _find(self, operation_id: str) -> OperationDecision | None:
        for event in self.journal.events():
            payload: Mapping[str, Any] = event.payload
            if event.event_type != "OUTCOME" or payload.get("kind") != "OPERATION_DECISION":
                continue
            if payload.get("operation_id") != operation_id:
                continue
            digest = payload.get("input_digest")
            attempt_id = payload.get("attempt_id")
            if not isinstance(digest, str) or not isinstance(attempt_id, str) or not attempt_id:
                raise OperationIdentityError("committed operation identity evidence is malformed")
            return OperationDecision(
                OperationIdentity(operation_id, digest),
                attempt_id,
                str(payload.get("decision", "")),
                event.sequence or 0,
            )
        return None
