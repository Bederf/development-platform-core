"""Controller-owned workspace lifecycle for GSD P046 T001-T003.

This module records ownership before workspace use and journals evidence before
release decisions. It deliberately performs no filesystem creation/deletion,
provider dispatch or harness invocation.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from .gsd_execution_journal import JournalError, JournalEvent, JournalStore


class WorkspaceOwnershipError(ValueError):
    """Raised when workspace ownership cannot be established safely."""


QUARANTINE_TRIGGERS = frozenset({
    "crash", "unknown_outcome", "contradictory_ownership", "collision", "stale_owner",
    "cleanup_failure",
})
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceOwnershipError(f"{field} must be a non-empty string")
    return value.strip()


def _absolute_path(value: str, field: str) -> str:
    candidate = Path(_required(value, field))
    if not candidate.is_absolute():
        raise WorkspaceOwnershipError(f"{field} must be an absolute path")
    return os.path.normpath(str(candidate))


def _state_root(value: str) -> str:
    result = _absolute_path(value, "state_root")
    if ".gsd-engine" in Path(result).parts:
        raise WorkspaceOwnershipError("controller state root cannot be legacy .gsd-engine")
    return result


def _identity_evidence_digest(identity: "WorkspaceIdentity", trigger: str) -> str:
    encoded = json.dumps(
        {"identity": identity.as_payload(), "trigger": trigger},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _payload_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WorkspaceIdentity:
    """Immutable controller identity for one mutating attempt workspace."""

    state_root: str
    run_id: str
    execution_id: str
    task_id: str
    attempt_id: str
    workspace_id: str
    workspace_root: str
    controller_epoch: int
    policy: str = "exclusive"

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_root", _state_root(self.state_root))
        object.__setattr__(self, "workspace_root", _absolute_path(self.workspace_root, "workspace_root"))
        for field in ("run_id", "execution_id", "task_id", "attempt_id", "workspace_id"):
            _required(getattr(self, field), field)
        if self.controller_epoch < 1:
            raise WorkspaceOwnershipError("controller epoch must be positive")
        if self.policy != "exclusive":
            raise WorkspaceOwnershipError("P5 T001 supports only exclusive ownership")

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceReservation:
    operation_id: str
    identity: WorkspaceIdentity
    ownership_state: str
    sequence: int
    quarantine_trigger: str | None = None
    quarantine_reason: str | None = None
    evidence_digest: str | None = None
    task_blocked: bool = False
    evidence_manifest_digest: str | None = None
    reconciliation_digest: str | None = None


class WorkspaceReservationController:
    """Journal-backed exclusive workspace reservation controller."""

    def __init__(self, journal: JournalStore, *, state_root: str, controller_epoch: int = 1) -> None:
        if controller_epoch < 1:
            raise WorkspaceOwnershipError("controller epoch must be positive")
        self.journal = journal
        self.state_root = _state_root(state_root)
        self.controller_epoch = controller_epoch
        if self.journal.controller_epoch > controller_epoch:
            raise WorkspaceOwnershipError("controller epoch is stale")
        self.journal.set_controller_epoch(controller_epoch)

    def reserve(self, identity: WorkspaceIdentity, *, operation_id: str) -> WorkspaceReservation:
        """Record one exclusive owner, returning an idempotent duplicate."""

        operation_id = _required(operation_id, "operation_id")
        self._validate_controller_identity(identity)
        # Collision inspection and journal append are one serialized critical
        # section so independent local controllers cannot both commit owners.
        with self._exclusive_journal_lock():
            existing = self._by_operation(operation_id)
            if existing is not None:
                if existing.identity != identity or existing.ownership_state != "ACTIVE":
                    raise WorkspaceOwnershipError("conflicting duplicate workspace reservation")
                return existing

            for reservation in self.replay_reservations():
                other = reservation.identity
                if other.workspace_id == identity.workspace_id or other.workspace_root == identity.workspace_root:
                    if reservation.ownership_state == "QUARANTINED":
                        raise WorkspaceOwnershipError("workspace is quarantined and cannot be reused")
                    trigger = "stale_owner" if other.controller_epoch < identity.controller_epoch else "collision"
                    self._append_quarantine_locked(
                        reservation,
                        trigger=trigger,
                        reason=f"reservation rejected by {trigger} evidence",
                        evidence_digest=_identity_evidence_digest(other, trigger),
                    )
                    if other.controller_epoch < identity.controller_epoch:
                        raise WorkspaceOwnershipError("stale workspace owner must be reconciled before reuse")
                    raise WorkspaceOwnershipError("workspace is already exclusively owned")

            event = JournalEvent(
                event_id=f"workspace-ownership:{operation_id}",
                event_type="OUTCOME",
                controller_epoch=self.controller_epoch,
                operation_id=operation_id,
                payload={
                    "kind": "WORKSPACE_OWNERSHIP_RESERVED",
                    "ownership_state": "ACTIVE",
                    "operation_id": operation_id,
                    **identity.as_payload(),
                },
            )
            try:
                committed = self.journal.append(event)
            except JournalError as exc:
                raise WorkspaceOwnershipError("workspace ownership could not be committed") from exc
            return WorkspaceReservation(operation_id, identity, "ACTIVE", committed.sequence or 0)

    def quarantine(self, operation_id: str, *, trigger: str, reason: str, evidence_digest: str) -> WorkspaceReservation:
        """Journal a fail-closed quarantine for an active workspace owner."""

        operation_id = _required(operation_id, "operation_id")
        self._validate_quarantine(trigger, reason, evidence_digest)
        with self._exclusive_journal_lock():
            reservation = self._by_operation(operation_id)
            if reservation is None:
                raise WorkspaceOwnershipError("cannot quarantine an unknown workspace owner")
            if reservation.ownership_state == "QUARANTINED":
                if reservation.quarantine_trigger != trigger or reservation.evidence_digest != evidence_digest:
                    raise WorkspaceOwnershipError("conflicting quarantine evidence; fail closed")
                return reservation
            return self._append_quarantine_locked(
                reservation, trigger=trigger, reason=reason, evidence_digest=evidence_digest
            )

    def recover_uncertain(self) -> tuple[WorkspaceReservation, ...]:
        """Quarantine owners whose journal shows crash or unknown evidence."""

        with self._exclusive_journal_lock():
            projection = self.journal.replay()
            uncertain = {operation_id: "crash" for operation_id in projection.incomplete_dispatch_intents}
            for event in projection.events:
                if event.event_type == "DISPATCH_OBSERVED" and event.payload.get("outcome") == "UNKNOWN":
                    uncertain[event.operation_id] = "unknown_outcome"
            for operation_id, trigger in sorted(uncertain.items()):
                reservation = self._by_operation(operation_id)
                if reservation is None or reservation.ownership_state != "ACTIVE":
                    continue
                self._append_quarantine_locked(
                    reservation,
                    trigger=trigger,
                    reason=f"recovery detected {trigger} evidence",
                    evidence_digest=_identity_evidence_digest(reservation.identity, trigger),
                )
            return self.replay_reservations()

    def observe_ownership(
        self,
        operation_id: str,
        *,
        observed_workspace_id: str,
        observed_workspace_root: str,
        evidence_digest: str,
    ) -> WorkspaceReservation:
        """Accept matching ownership evidence or quarantine contradictions."""

        operation_id = _required(operation_id, "operation_id")
        observed_workspace_id = _required(observed_workspace_id, "observed_workspace_id")
        observed_workspace_root = _absolute_path(observed_workspace_root, "observed_workspace_root")
        if not _DIGEST.fullmatch(evidence_digest):
            raise WorkspaceOwnershipError("ownership evidence requires a canonical SHA-256 digest")
        with self._exclusive_journal_lock():
            reservation = self._by_operation(operation_id)
            if reservation is None:
                raise WorkspaceOwnershipError("ownership observation has no reservation")
            if reservation.ownership_state == "QUARANTINED":
                return reservation
            if (
                reservation.identity.workspace_id != observed_workspace_id
                or reservation.identity.workspace_root != observed_workspace_root
            ):
                return self._append_quarantine_locked(
                    reservation,
                    trigger="contradictory_ownership",
                    reason="observed workspace ownership contradicts controller identity",
                    evidence_digest=evidence_digest,
                )
            return reservation

    def release(
        self,
        operation_id: str,
        *,
        reconciliation_digest: str,
        evidence_manifest: Mapping[str, Any],
        cleanup_succeeded: bool,
    ) -> WorkspaceReservation:
        """Preserve evidence, then record a release or fail-closed cleanup."""

        operation_id = _required(operation_id, "operation_id")
        if not _DIGEST.fullmatch(reconciliation_digest):
            raise WorkspaceOwnershipError("release requires a canonical reconciliation digest")
        if type(cleanup_succeeded) is not bool:
            raise WorkspaceOwnershipError("cleanup result must be explicit")
        with self._exclusive_journal_lock():
            reservation = self._by_operation(operation_id)
            if reservation is None:
                raise WorkspaceOwnershipError("cannot release an unknown workspace owner")
            if reservation.ownership_state == "RELEASED":
                if cleanup_succeeded is not True:
                    raise WorkspaceOwnershipError("conflicting duplicate workspace release")
                self._validate_evidence_manifest(reservation, evidence_manifest)
                manifest_digest = _payload_digest(evidence_manifest)
                if (
                    reservation.evidence_manifest_digest != manifest_digest
                    or reservation.reconciliation_digest != reconciliation_digest
                ):
                    raise WorkspaceOwnershipError("conflicting duplicate workspace release")
                return reservation
            self._validate_evidence_manifest(reservation, evidence_manifest)
            manifest = dict(evidence_manifest)
            manifest_digest = _payload_digest(manifest)
            evidence_event_id = f"workspace-evidence:{operation_id}:{manifest_digest}"
            outcome_event_id = (
                f"workspace-released:{operation_id}:{manifest_digest}"
                if cleanup_succeeded
                else f"workspace-cleanup-failed:{operation_id}:{manifest_digest}"
            )
            evidence_event = JournalEvent(
                event_id=evidence_event_id,
                event_type="OUTCOME",
                controller_epoch=self.controller_epoch,
                operation_id=operation_id,
                payload={
                    "kind": "WORKSPACE_EVIDENCE_PRESERVED",
                    "operation_id": operation_id,
                    "prior_state_sequence": reservation.sequence,
                    "manifest_digest": manifest_digest,
                    "reconciliation_digest": reconciliation_digest,
                    "identity": reservation.identity.as_payload(),
                    "manifest": manifest,
                },
            )
            outcome_kind = "WORKSPACE_RELEASED" if cleanup_succeeded else "WORKSPACE_CLEANUP_FAILED"
            outcome_payload = {
                "kind": outcome_kind,
                "operation_id": operation_id,
                "prior_state_sequence": reservation.sequence,
                "evidence_event_id": evidence_event_id,
                "manifest_digest": manifest_digest,
                "reconciliation_digest": reconciliation_digest,
                "identity": reservation.identity.as_payload(),
                "ownership_state": "RELEASED" if cleanup_succeeded else "QUARANTINED",
                "task_blocked": not cleanup_succeeded,
            }
            if not cleanup_succeeded:
                outcome_payload.update({
                    "quarantine_trigger": "cleanup_failure",
                    "quarantine_reason": "workspace cleanup failed after evidence preservation",
                    "evidence_digest": manifest_digest,
                })
            try:
                self.journal.append_batch((evidence_event, JournalEvent(
                    event_id=outcome_event_id,
                    event_type="OUTCOME",
                    controller_epoch=self.controller_epoch,
                    operation_id=operation_id,
                    payload=outcome_payload,
                )))
            except JournalError as exc:
                raise WorkspaceOwnershipError("workspace release could not be committed") from exc
            return self._by_operation(operation_id) or reservation

    @contextmanager
    def _exclusive_journal_lock(self):
        """Serialize ownership check/commit across local controller processes."""

        with self.journal.path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def replay_reservations(self) -> tuple[WorkspaceReservation, ...]:
        events = self.journal.replay().events
        reservations: list[WorkspaceReservation] = []
        for event in events:
            if event.event_type != "OUTCOME" or event.payload.get("kind") != "WORKSPACE_OWNERSHIP_RESERVED":
                continue
            payload: Mapping[str, Any] = event.payload
            required = {
                "operation_id", "ownership_state", "state_root", "run_id", "execution_id",
                "task_id", "attempt_id", "workspace_id", "workspace_root", "controller_epoch", "policy",
            }
            if not required.issubset(payload):
                raise WorkspaceOwnershipError("workspace ownership evidence is malformed")
            if payload["operation_id"] != event.operation_id or payload["ownership_state"] != "ACTIVE":
                raise WorkspaceOwnershipError("workspace ownership evidence identity is invalid")
            identity = WorkspaceIdentity(
                state_root=str(payload["state_root"]), run_id=str(payload["run_id"]),
                execution_id=str(payload["execution_id"]), task_id=str(payload["task_id"]),
                attempt_id=str(payload["attempt_id"]), workspace_id=str(payload["workspace_id"]),
                workspace_root=str(payload["workspace_root"]), controller_epoch=int(payload["controller_epoch"]),
                policy=str(payload["policy"]),
            )
            if identity.state_root != self.state_root:
                raise WorkspaceOwnershipError("workspace ownership crosses controller state root")
            reservations.append(WorkspaceReservation(event.operation_id, identity, "ACTIVE", event.sequence or 0))
        reservation_by_operation: dict[str, WorkspaceReservation] = {}
        for reservation in reservations:
            if reservation.operation_id in reservation_by_operation:
                raise WorkspaceOwnershipError("journal contains duplicate workspace reservation operation")
            reservation_by_operation[reservation.operation_id] = reservation

        quarantine_events: dict[str, list[JournalEvent]] = {}
        for event in events:
            if event.event_type != "OUTCOME" or event.payload.get("kind") != "WORKSPACE_OWNERSHIP_QUARANTINED":
                continue
            quarantine_events.setdefault(event.operation_id, []).append(event)

        orphaned = set(quarantine_events).difference(reservation_by_operation)
        if orphaned:
            raise WorkspaceOwnershipError("quarantine evidence has no workspace reservation")
        if any(len(events_for_operation) != 1 for events_for_operation in quarantine_events.values()):
            raise WorkspaceOwnershipError("workspace operation has multiple quarantine evidence records")

        updated: list[WorkspaceReservation] = []
        for reservation in reservations:
            events_for_operation = quarantine_events.get(reservation.operation_id)
            if events_for_operation is None:
                updated.append(reservation)
                continue
            event = events_for_operation[0]
            payload = event.payload
            required = {
                "kind", "ownership_state", "operation_id", "prior_reservation_sequence",
                "quarantine_trigger", "quarantine_reason", "evidence_digest", "task_blocked",
                "state_root", "run_id", "execution_id", "task_id", "attempt_id",
                "workspace_id", "workspace_root", "controller_epoch", "policy",
            }
            if not required.issubset(payload):
                raise WorkspaceOwnershipError("quarantine ownership evidence is malformed")
            if (
                payload["operation_id"] != event.operation_id
                or payload["ownership_state"] != "QUARANTINED"
                or payload["task_blocked"] is not True
                or event.controller_epoch != reservation.identity.controller_epoch
            ):
                raise WorkspaceOwnershipError("quarantine ownership evidence identity is invalid")
            if payload["prior_reservation_sequence"] != reservation.sequence:
                raise WorkspaceOwnershipError("quarantine lineage does not match reservation")
            if event.sequence is None or event.sequence <= reservation.sequence:
                raise WorkspaceOwnershipError("quarantine evidence sequence is invalid")
            trigger = payload.get("quarantine_trigger")
            reason = payload.get("quarantine_reason")
            evidence_digest = payload.get("evidence_digest")
            self._validate_quarantine(trigger, reason, evidence_digest)
            try:
                quarantine_identity = WorkspaceIdentity(
                    state_root=str(payload["state_root"]), run_id=str(payload["run_id"]),
                    execution_id=str(payload["execution_id"]), task_id=str(payload["task_id"]),
                    attempt_id=str(payload["attempt_id"]), workspace_id=str(payload["workspace_id"]),
                    workspace_root=str(payload["workspace_root"]),
                    controller_epoch=int(payload["controller_epoch"]),
                    policy=str(payload["policy"]),
                )
            except (TypeError, ValueError) as exc:
                raise WorkspaceOwnershipError("quarantine ownership evidence identity is malformed") from exc
            if quarantine_identity != reservation.identity:
                raise WorkspaceOwnershipError("quarantine ownership evidence identity does not match reservation")
            updated.append(
                WorkspaceReservation(
                    reservation.operation_id, reservation.identity, "QUARANTINED", event.sequence or 0,
                    trigger, reason, evidence_digest, payload.get("task_blocked") is True,
                )
            )

        current_by_operation = {reservation.operation_id: reservation for reservation in updated}
        evidence_events: dict[str, list[JournalEvent]] = {}
        outcome_events: dict[str, list[JournalEvent]] = {}
        for event in events:
            if event.event_type != "OUTCOME":
                continue
            kind = event.payload.get("kind")
            if kind == "WORKSPACE_EVIDENCE_PRESERVED":
                evidence_events.setdefault(event.operation_id, []).append(event)
            elif kind in {"WORKSPACE_RELEASED", "WORKSPACE_CLEANUP_FAILED"}:
                outcome_events.setdefault(event.operation_id, []).append(event)
        for operation_id in set(evidence_events) | set(outcome_events):
            if operation_id not in current_by_operation:
                raise WorkspaceOwnershipError("release evidence has no workspace reservation")
        if any(len(items) != 1 for items in evidence_events.values()):
            raise WorkspaceOwnershipError("workspace operation has multiple evidence manifests")
        if any(len(items) != 1 for items in outcome_events.values()):
            raise WorkspaceOwnershipError("workspace operation has multiple release outcomes")
        if set(evidence_events) != set(outcome_events):
            raise WorkspaceOwnershipError("workspace evidence and cleanup outcome are incomplete")

        finalized: list[WorkspaceReservation] = []
        for reservation in updated:
            evidence_items = evidence_events.get(reservation.operation_id)
            if evidence_items is None:
                finalized.append(reservation)
                continue
            evidence_event = evidence_items[0]
            evidence_payload = evidence_event.payload
            required_evidence = {
                "kind", "operation_id", "prior_state_sequence", "manifest_digest",
                "reconciliation_digest", "identity", "manifest",
            }
            if not required_evidence.issubset(evidence_payload):
                raise WorkspaceOwnershipError("workspace evidence manifest is malformed")
            if (
                evidence_payload["operation_id"] != evidence_event.operation_id
                or evidence_event.controller_epoch != reservation.identity.controller_epoch
                or evidence_payload["prior_state_sequence"] != reservation.sequence
                or evidence_event.sequence is None
                or evidence_event.sequence <= reservation.sequence
                or not _DIGEST.fullmatch(evidence_payload["reconciliation_digest"])
            ):
                raise WorkspaceOwnershipError("workspace evidence manifest lineage is invalid")
            identity_payload = evidence_payload["identity"]
            if not isinstance(identity_payload, Mapping) or dict(identity_payload) != reservation.identity.as_payload():
                raise WorkspaceOwnershipError("workspace evidence identity does not match reservation")
            manifest = evidence_payload["manifest"]
            if not isinstance(manifest, Mapping) or _payload_digest(manifest) != evidence_payload["manifest_digest"]:
                raise WorkspaceOwnershipError("workspace evidence manifest digest is invalid")
            self._validate_evidence_manifest(reservation, manifest)

            outcome_event = outcome_events[reservation.operation_id][0]
            outcome_payload = outcome_event.payload
            required_outcome = {
                "kind", "operation_id", "prior_state_sequence", "evidence_event_id",
                "manifest_digest", "reconciliation_digest", "identity", "ownership_state",
                "task_blocked",
            }
            if not required_outcome.issubset(outcome_payload):
                raise WorkspaceOwnershipError("workspace cleanup outcome is malformed")
            if (
                outcome_payload["operation_id"] != outcome_event.operation_id
                or outcome_payload["prior_state_sequence"] != reservation.sequence
                or outcome_payload["evidence_event_id"] != evidence_event.event_id
                or outcome_payload["manifest_digest"] != evidence_payload["manifest_digest"]
                or outcome_payload["reconciliation_digest"] != evidence_payload["reconciliation_digest"]
                or outcome_payload["identity"] != reservation.identity.as_payload()
                or outcome_event.sequence is None
                or outcome_event.sequence <= evidence_event.sequence
                or outcome_event.controller_epoch != reservation.identity.controller_epoch
            ):
                raise WorkspaceOwnershipError("workspace cleanup outcome lineage is invalid")
            if outcome_payload["kind"] == "WORKSPACE_RELEASED":
                if outcome_payload["ownership_state"] != "RELEASED" or outcome_payload["task_blocked"] is not False:
                    raise WorkspaceOwnershipError("workspace release outcome is invalid")
                finalized.append(WorkspaceReservation(
                    reservation.operation_id, reservation.identity, "RELEASED", outcome_event.sequence or 0,
                    evidence_manifest_digest=evidence_payload["manifest_digest"],
                    reconciliation_digest=evidence_payload["reconciliation_digest"],
                ))
            else:
                if (
                    outcome_payload["ownership_state"] != "QUARANTINED"
                    or outcome_payload["task_blocked"] is not True
                    or outcome_payload.get("quarantine_trigger") != "cleanup_failure"
                    or outcome_payload.get("evidence_digest") != evidence_payload["manifest_digest"]
                ):
                    raise WorkspaceOwnershipError("workspace cleanup failure outcome is invalid")
                reason = outcome_payload.get("quarantine_reason")
                self._validate_quarantine("cleanup_failure", reason, evidence_payload["manifest_digest"])
                finalized.append(WorkspaceReservation(
                    reservation.operation_id, reservation.identity, "QUARANTINED", outcome_event.sequence or 0,
                    "cleanup_failure", reason, evidence_payload["manifest_digest"], True,
                    evidence_payload["manifest_digest"], evidence_payload["reconciliation_digest"],
                ))
        return tuple(finalized)

    def _append_quarantine_locked(
        self,
        reservation: WorkspaceReservation,
        *,
        trigger: str,
        reason: str,
        evidence_digest: str,
    ) -> WorkspaceReservation:
        self._validate_quarantine(trigger, reason, evidence_digest)
        event = JournalEvent(
            event_id=f"workspace-quarantine:{reservation.operation_id}:{trigger}:{evidence_digest}",
            event_type="OUTCOME",
            controller_epoch=self.controller_epoch,
            operation_id=reservation.operation_id,
            payload={
                "kind": "WORKSPACE_OWNERSHIP_QUARANTINED",
                "ownership_state": "QUARANTINED",
                "operation_id": reservation.operation_id,
                "prior_reservation_sequence": reservation.sequence,
                "quarantine_trigger": trigger,
                "quarantine_reason": reason,
                "evidence_digest": evidence_digest,
                "task_blocked": True,
                **reservation.identity.as_payload(),
            },
        )
        try:
            committed = self.journal.append(event)
        except JournalError as exc:
            raise WorkspaceOwnershipError("workspace quarantine could not be committed") from exc
        return WorkspaceReservation(
            reservation.operation_id, reservation.identity, "QUARANTINED", committed.sequence or 0,
            trigger, reason, evidence_digest, True,
        )

    @staticmethod
    def _validate_quarantine(trigger: str, reason: str, evidence_digest: str) -> None:
        if trigger not in QUARANTINE_TRIGGERS:
            raise WorkspaceOwnershipError("unsupported workspace quarantine trigger")
        _required(reason, "quarantine reason")
        if not isinstance(evidence_digest, str) or not _DIGEST.fullmatch(evidence_digest):
            raise WorkspaceOwnershipError("workspace quarantine requires a canonical SHA-256 evidence digest")

    @staticmethod
    def _validate_evidence_manifest(
        reservation: WorkspaceReservation,
        manifest: Mapping[str, Any],
    ) -> None:
        if not isinstance(manifest, Mapping):
            raise WorkspaceOwnershipError("workspace evidence manifest is required")
        if manifest.get("operation_id") != reservation.operation_id:
            raise WorkspaceOwnershipError("workspace evidence manifest operation is invalid")
        identity = manifest.get("identity")
        if not isinstance(identity, Mapping) or dict(identity) != reservation.identity.as_payload():
            raise WorkspaceOwnershipError("workspace evidence manifest identity is invalid")
        if not isinstance(manifest.get("artifacts"), list):
            raise WorkspaceOwnershipError("workspace evidence manifest artifacts are required")

    def _by_operation(self, operation_id: str) -> WorkspaceReservation | None:
        matches = [item for item in self.replay_reservations() if item.operation_id == operation_id]
        if len(matches) > 1:
            raise WorkspaceOwnershipError("journal contains duplicate workspace reservation operation")
        return matches[0] if matches else None

    def _validate_controller_identity(self, identity: WorkspaceIdentity) -> None:
        if not isinstance(identity, WorkspaceIdentity):
            raise WorkspaceOwnershipError("workspace reservation requires WorkspaceIdentity")
        if identity.state_root != self.state_root:
            raise WorkspaceOwnershipError("workspace identity is outside controller state root")
        if identity.controller_epoch != self.controller_epoch:
            raise WorkspaceOwnershipError("workspace identity controller epoch does not match controller")
