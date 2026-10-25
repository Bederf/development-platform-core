"""Build a bounded, objective-scoped projection for provider startup.

The authoritative startup context and source documents remain unchanged. This
module controls only what is placed inline in a provider prompt; excluded
material remains addressable through explicit on-demand source references.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any


class ContextProjectionError(ValueError):
    """Raised when a bounded projection cannot be produced safely."""


_WORD_RE = re.compile(r"[a-z0-9]+")
_CLOSED_RE = re.compile(r"\b(closed|complete(?:d)?|archived|superseded|cancelled)\b", re.I)
_HISTORY_HEADING_RE = re.compile(r"^(?:#+\s*)?(?:version|change|session|phase)\s+history\b", re.I)
_NEXT_ACTION_RE = re.compile(r"^\*\*Next(?: action)?:\*\*\s*(.+)$", re.I | re.M)
_STATUS_RE = re.compile(r"^\*\*Status:?\*\*\s*(.+)$", re.I | re.M)
_TERMINAL_STATUS_RE = re.compile(
    r"^[*_\s]*(?:fully\s+)?(closed|complete(?:d)?|resolved|archived|superseded)\b",
    re.I,
)


def estimate_tokens(text: str) -> int:
    """Return the conservative character-based estimate used by Radix."""

    return max(1, math.ceil(len(text) / 4)) if text else 0


def extract_active_actions(text: str) -> list[str]:
    """Extract actions from non-closed Markdown ``###`` sections."""

    actions: list[str] = []
    for block in re.split(r"\n(?=###\s+)", text):
        lines = block.splitlines()
        if not lines or not lines[0].lstrip().startswith("### "):
            continue
        if _CLOSED_RE.search(lines[0]):
            continue
        status = _STATUS_RE.search(block)
        if status and _TERMINAL_STATUS_RE.search(status.group(1)):
            continue
        match = _NEXT_ACTION_RE.search(block)
        if match:
            action = match.group(1).strip()
            if action and action not in actions:
                actions.append(action)
    return actions


class StartupContextProjector:
    """Compile current authority into ``startup-context-projection.v1``."""

    schema = "startup-context-projection.v1"

    def __init__(self, *, max_tokens: int = 6000) -> None:
        if not isinstance(max_tokens, int) or not 1 <= max_tokens <= 8000:
            raise ContextProjectionError("max_tokens must be an integer between 1 and 8000")
        self.max_tokens = max_tokens

    def project(
        self,
        *,
        project_id: str,
        objective: str,
        tasks: Iterable[Mapping[str, Any]],
        brief: Mapping[str, Any],
        sections: Iterable[Mapping[str, Any]],
        source_documents: Iterable[Mapping[str, Any]],
        working_state: Mapping[str, Any] | None = None,
        working_state_lineage: Mapping[str, Any] | None = None,
        evidence_references: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        project_id = self._required_string(project_id, "project_id")
        objective = self._required_string(objective, "objective")
        normalized_brief = self._brief(brief)
        task_selection = self._select_task(objective, tasks)
        on_demand: list[dict[str, str]] = []
        on_demand_keys: set[tuple[str, str]] = set()

        def defer(source_id: str, path: str, reason: str) -> None:
            key = (source_id, path)
            if key not in on_demand_keys:
                on_demand.append({"source_id": source_id, "path": path, "reason": reason})
                on_demand_keys.add(key)

        for source in source_documents:
            source_id, path = self._source_reference(source)
            defer(source_id, path, "authoritative source; load only when required")

        candidates: list[tuple[int, int, dict[str, Any], bool]] = []
        seen_hashes: set[str] = set()
        for raw in sections:
            item, mandatory = self._section(raw)
            excluded_reason = self._excluded_reason(item)
            if excluded_reason is not None:
                defer(item["source_id"], item["path"], excluded_reason)
                continue
            if item["content_hash"] in seen_hashes:
                continue
            seen_hashes.add(item["content_hash"])
            relevance = self._relevance(objective, item["text"] + " " + item["section_id"])
            if not mandatory and relevance == 0:
                defer(item["source_id"], item["path"], "not relevant to current objective")
                continue
            authority_rank = 2 if item["authority"] == "executable" else 1
            candidates.append((1 if mandatory else 0, relevance * 10 + authority_rank, item, mandatory))

        candidates = sorted(
            enumerate(candidates),
            key=lambda entry: (-entry[1][0], -entry[1][1], entry[0]),
        )
        used = estimate_tokens(objective + "\n" + (normalized_brief["text"] or ""))
        if used > self.max_tokens:
            raise ContextProjectionError("objective and session brief exceed the context budget")
        inline: list[dict[str, Any]] = []
        truncated = False
        for _, (_, _, item, mandatory) in candidates:
            tokens = item["estimated_tokens"]
            if used + tokens > self.max_tokens:
                if mandatory:
                    raise ContextProjectionError(
                        f"mandatory section {item['section_id']!r} exceeds the context budget"
                    )
                truncated = True
                defer(item["source_id"], item["path"], "context budget")
                continue
            inline.append({key: value for key, value in item.items() if not key.startswith("_")})
            used += tokens

        projection = {
            "schema": self.schema,
            "project_id": project_id,
            "objective": objective,
            "task_selection": task_selection,
            "budget": {
                "max_tokens": self.max_tokens,
                "estimated_tokens": used,
                "truncated": truncated,
            },
            "brief": normalized_brief,
            "inline_sections": inline,
            "on_demand_sources": on_demand,
            "working_state": self._working_state(working_state),
        }
        if working_state_lineage is not None:
            projection["working_state_lineage"] = self._lineage(working_state_lineage)
        if evidence_references is not None:
            projection["evidence_references"] = self._evidence_references(evidence_references)
        return projection

    def render_prompt(self, projection: Mapping[str, Any]) -> str:
        if projection.get("schema") != self.schema:
            raise ContextProjectionError("unsupported startup context projection")
        lines = [
            "Project startup context",
            "",
            f"Project: {projection['project_id']}",
            f"Current objective: {projection['objective']}",
            f"Selected knowledge task: {projection['task_selection']['task_id'] or 'none'}",
        ]
        brief = projection["brief"]
        if brief.get("text"):
            lines.extend(["", "Session brief", str(brief["text"])])
        working_state = projection.get("working_state")
        if working_state is not None:
            lines.extend(
                [
                    "",
                    "Derived working state (orientation only; authoritative sources prevail)",
                    f"Phase: {working_state['phase']}",
                    f"Completed: {', '.join(working_state['completed_summary']) or 'none'}",
                    f"Discoveries: {', '.join(working_state['discovery_summary']) or 'none'}",
                    f"Failures: {', '.join(working_state['failure_summary']) or 'none'}",
                    f"Next: {working_state['next_step']}",
                    f"Blocker: {working_state['blocker']}",
                ]
            )
        lineage = projection.get("working_state_lineage")
        if lineage is not None:
            lines.extend(
                [
                    "",
                    "Working-state resume lineage",
                    f"New session: {lineage['session_id']}",
                    f"Prior session: {lineage['prior_session_id']}",
                    f"Prior checkpoint: {lineage['resumed_from_candidate_id']}",
                ]
            )
        evidence = projection.get("evidence_references")
        if evidence:
            lines.extend(["", "Bounded evidence references"])
            for item in evidence:
                lines.append(f"- {item['ref']}: {item['path']} ({item['status']})")
        sections = projection["inline_sections"]
        if sections:
            lines.extend(["", "Current authority"])
            for item in sections:
                lines.extend([f"[{item['source_id']} — {item['section_id']}]", str(item["text"])])
        sources = projection["on_demand_sources"]
        if sources:
            lines.extend(["", "On-demand authoritative sources", "Load only when the task requires it:"])
            for item in sources:
                lines.append(f"- {item['source_id']}: {item['path']} ({item['reason']})")
        lines.extend(
            [
                "",
                "Do not reread every on-demand source during bootstrap. Resolve conflicts by consulting only the specific authoritative section needed.",
            ]
        )
        return "\n".join(lines) + "\n"

    def _select_task(
        self, objective: str, tasks: Iterable[Mapping[str, Any]]
    ) -> dict[str, str | None]:
        ranked: list[tuple[int, int, str]] = []
        objective_words = self._words(objective)
        for position, task in enumerate(tasks):
            task_id = self._required_string(task.get("id"), "tasks[].id")
            description = self._required_string(task.get("description"), "tasks[].description")
            overlap = len(objective_words & self._words(task_id + " " + description))
            if overlap:
                ranked.append((overlap, -position, task_id))
        if not ranked:
            return {
                "strategy": "objective_relevance",
                "task_id": None,
                "reason": "no declared task overlaps the current objective; no unrelated default was used",
            }
        overlap, _, task_id = max(ranked)
        return {
            "strategy": "objective_relevance",
            "task_id": task_id,
            "reason": f"selected by objective relevance ({overlap} matching term(s))",
        }

    @staticmethod
    def _words(text: str) -> set[str]:
        return {word for word in _WORD_RE.findall(text.lower()) if len(word) > 2}

    def _relevance(self, objective: str, text: str) -> int:
        return len(self._words(objective) & self._words(text))

    @staticmethod
    def _brief(brief: Mapping[str, Any]) -> dict[str, str | None]:
        status = brief.get("status")
        if status not in {"accepted", "regenerated", "unavailable"}:
            raise ContextProjectionError("brief.status is invalid")
        path = brief.get("path")
        text = brief.get("text")
        if path is not None and not isinstance(path, str):
            raise ContextProjectionError("brief.path must be a string or null")
        if text is not None and not isinstance(text, str):
            raise ContextProjectionError("brief.text must be a string or null")
        return {"status": status, "path": path, "text": text}

    def _section(self, raw: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        kind = raw.get("kind")
        if kind not in {"active", "reference", "history", "template", "empty"}:
            raise ContextProjectionError("sections[].kind is invalid")
        authority = raw.get("authority")
        if authority not in {"executable", "reference"}:
            raise ContextProjectionError("sections[].authority is invalid")
        text = self._required_string(raw.get("text"), "sections[].text")
        content_hash = self._required_string(raw.get("content_hash"), "sections[].content_hash")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash):
            raise ContextProjectionError("sections[].content_hash is invalid")
        mandatory = raw.get("mandatory", False)
        if not isinstance(mandatory, bool):
            raise ContextProjectionError("sections[].mandatory must be boolean")
        return {
            "source_id": self._required_string(raw.get("source_id"), "sections[].source_id"),
            "path": self._required_string(raw.get("path"), "sections[].path"),
            "section_id": self._required_string(raw.get("section_id"), "sections[].section_id"),
            "kind": kind if kind in {"active", "reference"} else "reference",
            "authority": authority,
            "text": text,
            "content_hash": content_hash,
            "estimated_tokens": estimate_tokens(text),
            "_input_kind": kind,
        }, mandatory

    @staticmethod
    def _excluded_reason(item: Mapping[str, Any]) -> str | None:
        input_kind = item.get("_input_kind")
        if input_kind in {"history", "template", "empty"}:
            return f"{input_kind} content"
        heading = str(item["section_id"]).strip()
        text = str(item["text"]).strip()
        if _CLOSED_RE.search(heading):
            return "closed or superseded content"
        if _HISTORY_HEADING_RE.search(heading) or _HISTORY_HEADING_RE.search(text.splitlines()[0]):
            return "history content"
        if not re.search(r"[A-Za-z0-9]", text):
            return "empty content"
        return None

    def _source_reference(self, source: Mapping[str, Any]) -> tuple[str, str]:
        return (
            self._required_string(source.get("source_id"), "source_documents[].source_id"),
            self._required_string(source.get("path"), "source_documents[].path"),
        )

    @staticmethod
    def _working_state(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        required = {
            "candidate_id", "project_id", "session_id", "gsd_ref", "session_record_refs",
            "source_digests", "objective", "phase", "completed_summary", "discovery_summary",
            "failure_summary", "next_step", "blocker", "checkpointed_at", "reason",
            "projection_digest",
        }
        if set(value) != required:
            raise ContextProjectionError("working_state is not a bounded derived candidate")
        forbidden = {
            "authorization", "credentials", "execute", "policy_decision", "prompt",
            "raw_prompt", "raw_tool_output",
        }
        if forbidden.intersection(value):
            raise ContextProjectionError("working_state contains forbidden authority material")
        if value["project_id"] == "":
            raise ContextProjectionError("working_state.project_id is invalid")
        return {key: value[key] for key in required}

    @staticmethod
    def _lineage(value: Mapping[str, Any]) -> dict[str, str]:
        required = {"session_id", "resumed_from_candidate_id", "source_checkpoint_digest", "prior_session_id"}
        if set(value) != required or any(not isinstance(value[key], str) or not value[key].strip() for key in required):
            raise ContextProjectionError("working_state_lineage is not bounded")
        return {key: str(value[key]) for key in required}

    @staticmethod
    def _evidence_references(values: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for value in values:
            if set(value) != {"ref", "path", "status"} or value["status"] not in {"available", "unavailable"}:
                raise ContextProjectionError("evidence reference is not bounded")
            if any(not isinstance(value[key], str) or not value[key].strip() for key in ("ref", "path")):
                raise ContextProjectionError("evidence reference requires ref and path")
            result.append({"ref": value["ref"], "path": value["path"], "status": value["status"]})
        return result

    @staticmethod
    def _required_string(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ContextProjectionError(f"{field} must be a non-empty string")
        return value.strip()
