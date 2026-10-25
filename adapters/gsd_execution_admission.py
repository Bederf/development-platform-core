"""Bounded P044 controller-derived readiness and admission primitives.

This module owns neither provider dispatch nor workspace management. It binds a
validated graph to deterministic readiness and records one idempotent admission
reservation through the accepted P043 journal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from adapters.gsd_execution_journal import JournalEvent, JournalStore
from adapters.gsd_execution_state import AttemptState, ExecutionStateError, TaskState
from adapters.phase_specification import validate_execution_plan


class AdmissionError(ValueError):
    """Raised when readiness or admission cannot be established safely."""


@dataclass(frozen=True)
class GraphTask:
    task_id: str
    predecessors: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoundGraph:
    specification_hash: str
    graph_revision: str
    tasks: tuple[GraphTask, ...]
    phase_id: str | None = None
    specification_id: str | None = None
    specification_version: str | None = None
    plan_digest: str | None = None

    @classmethod
    def from_execution_plan(
        cls,
        specification: Mapping[str, Any],
        plan: Mapping[str, Any],
        *,
        graph_revision: str,
    ) -> "BoundGraph":
        """Bind a graph only after Core's existing validators accept its inputs."""
        resolution = validate_execution_plan(specification, plan)
        planned_tasks = plan.get("tasks")
        if not isinstance(planned_tasks, list):
            raise AdmissionError("execution plan tasks are unavailable")
        tasks = tuple(
            GraphTask(str(item["task_id"]), tuple(item.get("depends_on", ())))
            for item in planned_tasks
        )
        encoded = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
        plan_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        return cls(
            resolution.specification_hash,
            graph_revision,
            tasks,
            resolution.phase_id,
            resolution.specification_id,
            resolution.version,
            plan_digest,
        )

    def __post_init__(self) -> None:
        if not self.specification_hash or not self.graph_revision or not self.tasks:
            raise AdmissionError("graph identity and tasks are required")
        ids = [task.task_id for task in self.tasks]
        if any(not task_id for task_id in ids) or len(ids) != len(set(ids)):
            raise AdmissionError("graph task identities must be unique")
        known = set(ids)
        edges = {task.task_id: set(task.predecessors) for task in self.tasks}
        if any(predecessor not in known for values in edges.values() for predecessor in values):
            raise AdmissionError("graph predecessor is unknown")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise AdmissionError("graph contains a dependency cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for predecessor in edges[task_id]:
                visit(predecessor)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in ids:
            visit(task_id)

    def task(self, task_id: str) -> GraphTask:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        raise AdmissionError(f"unknown graph task: {task_id}")


@dataclass(frozen=True)
class AdmissionDecision:
    operation_id: str
    task_id: str
    attempt_id: str
    workspace_slot_id: str
    graph_revision: str
    sequence: int
    workspace_slot: str = ""


class AdmissionController:
    """Derive readiness and journal one bounded admission decision."""

    def __init__(self, journal: JournalStore, *, controller_epoch: int = 1):
        if controller_epoch < 1:
            raise AdmissionError("controller epoch must be positive")
        self.journal = journal
        self.controller_epoch = controller_epoch
        if self.journal.controller_epoch > controller_epoch:
            raise AdmissionError("controller epoch is stale")
        self.journal.set_controller_epoch(controller_epoch)

    @staticmethod
    def ready_tasks(
        graph: BoundGraph,
        task_states: Mapping[str, TaskState],
        *,
        attempt_states: Mapping[str, AttemptState] | None = None,
        caller_ready: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        if set(task_states) != {task.task_id for task in graph.tasks}:
            raise AdmissionError("task state projection diverges from bound graph")
        ready: list[str] = []
        for task in graph.tasks:
            if task_states[task.task_id] is not TaskState.PENDING:
                continue
            predecessor_states = [task_states[item] for item in task.predecessors]
            if all(state is TaskState.SUCCEEDED for state in predecessor_states):
                if attempt_states is not None and any(
                    attempt_states.get(item) is not AttemptState.SUCCEEDED
                    for item in task.predecessors
                ):
                    continue
                ready.append(task.task_id)
        result = tuple(sorted(ready))
        if caller_ready is not None and tuple(caller_ready) != result:
            raise AdmissionError("caller-supplied readiness conflicts with controller state")
        return result

    def admit(
        self,
        graph: BoundGraph,
        task_states: Mapping[str, TaskState],
        *,
        task_id: str,
        attempt_id: str,
        operation_id: str,
        workspace_slot_id: str | None = None,
        capacity: int,
        active_admissions: int | None = None,
        workspace_slot_available: bool = True,
        workspace_slot: str | None = None,
        authorization_satisfied: bool = True,
    ) -> AdmissionDecision:
        if not operation_id or not attempt_id:
            raise AdmissionError("admission identity is required")
        existing = self._existing_admission(operation_id)
        if existing is not None:
            if (
                existing.task_id != task_id
                or existing.attempt_id != attempt_id
                or (workspace_slot_id is not None and existing.workspace_slot_id != workspace_slot_id)
                or existing.graph_revision != graph.graph_revision
            ):
                raise AdmissionError("conflicting duplicate admission identity")
            return existing
        if any(item.task_id == task_id for item in self.replay_admissions()):
            raise AdmissionError("task already has an admission reservation")
        workspace_slot_id = workspace_slot_id or f"slot:{task_id}:{attempt_id}"
        if not workspace_slot_id:
            raise AdmissionError("workspace slot identity is required")
        committed_count = len(self.replay_admissions())
        if active_admissions is not None and active_admissions != committed_count:
            raise AdmissionError("caller admission count conflicts with journal state")
        if capacity < 1 or committed_count >= capacity:
            raise AdmissionError("controller capacity does not permit admission")
        if not workspace_slot_available:
            raise AdmissionError("admission workspace condition is unavailable")
        slot = workspace_slot or f"slot:{task_id}"
        occupied = {
            str(event.payload["slot"]): event.operation_id
            for event in self.journal.replay().events
            if event.payload.get("kind") == "WORKSPACE_SLOT_RESERVATION"
            and "slot" in event.payload
        }
        if slot in occupied and occupied[slot] != operation_id:
            raise AdmissionError("workspace slot is already reserved")
        if not authorization_satisfied:
            raise AdmissionError("admission authorization condition is unsatisfied")
        if task_id not in self.ready_tasks(graph, task_states):
            raise AdmissionError("task is not controller-ready")
        graph.task(task_id)
        event_id = f"admission:{operation_id}"
        payload = {
            "admission": "COMMITTED",
            "attempt_id": attempt_id,
            "task_id": task_id,
            "graph_revision": graph.graph_revision,
            "specification_hash": graph.specification_hash,
            "workspace_slot_id": workspace_slot_id,
            "state": AttemptState.CREATED.value,
        }
        try:
            committed, _slot_record = self.journal.append_batch([
                JournalEvent(
                    event_id,
                    "ATTEMPT_STATE",
                    self.controller_epoch,
                    operation_id,
                    payload,
                ),
                JournalEvent(
                    f"workspace-slot:{operation_id}",
                    "OUTCOME",
                    self.controller_epoch,
                    operation_id,
                    {"kind": "WORKSPACE_SLOT_RESERVATION", "slot": slot, "task_id": task_id},
                ),
            ])
        except (ValueError, ExecutionStateError) as exc:
            raise AdmissionError(str(exc)) from exc
        return AdmissionDecision(
            operation_id,
            task_id,
            attempt_id,
            workspace_slot_id,
            graph.graph_revision,
            committed.sequence or 0,
            slot,
        )

    def _existing_admission(self, operation_id: str) -> AdmissionDecision | None:
        matches = [item for item in self.replay_admissions() if item.operation_id == operation_id]
        if len(matches) > 1:
            raise AdmissionError("journal contains duplicate admission operation")
        if matches:
            return matches[0]
        return None

    def replay_admissions(self) -> tuple[AdmissionDecision, ...]:
        decisions: list[AdmissionDecision] = []
        for event in self.journal.replay().events:
            if event.event_type != "ATTEMPT_STATE" or event.payload.get("admission") != "COMMITTED":
                continue
            required = {"task_id", "attempt_id", "graph_revision", "workspace_slot_id"}
            if not required.issubset(event.payload):
                raise AdmissionError("admission projection is malformed")
            decisions.append(
                AdmissionDecision(
                    event.operation_id,
                    str(event.payload["task_id"]),
                    str(event.payload["attempt_id"]),
                    str(event.payload["workspace_slot_id"]),
                    str(event.payload["graph_revision"]),
                    event.sequence or 0,
                    str(next(
                        (
                            slot_event.payload["slot"]
                            for slot_event in self.journal.replay().events
                            if slot_event.operation_id == event.operation_id
                            and slot_event.payload.get("kind") == "WORKSPACE_SLOT_RESERVATION"
                        ),
                        "",
                    )),
                )
            )
        return tuple(decisions)
