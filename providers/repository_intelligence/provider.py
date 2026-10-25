"""RepositoryIntelligenceProvider: the first production provider satisfying
`repository-intelligence.v1`, wrapping `code-review-graph`.

Interface invariant (Phase 005): only `capabilities()`, `refresh()`,
`status()`, `collect_context()`, `health()` are exposed. This module must not
import or depend on Radix, GSD, Forge, Herdr, Claude, or Codex — consumers
depend on the contract, never on another consumer's implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any

from .context_retrieval import bound_context, retrieve_context
from .freshness import GraphSnapshot, inspect_graph, refresh_graph

STATUS_CURRENT = "CURRENT"
STATUS_REFRESHED = "REFRESHED"
STATUS_DEGRADED = "DEGRADED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
TRUSTED_STATUSES = {STATUS_CURRENT, STATUS_REFRESHED}


def _freshness_evidence(snapshot: GraphSnapshot) -> list[str]:
    evidence = [
        f"indexed_files={len(snapshot.indexed_hashes)}",
        f"working_tree_files={len(snapshot.current_files)}",
        f"remaining_mismatches={len(snapshot.mismatches)}",
    ]
    for key in ("git_branch", "git_head_sha", "last_updated", "last_build_type"):
        value = snapshot.metadata.get(key)
        if value:
            evidence.append(f"{key}={value}")
    return evidence


def _current_git_head(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    head = result.stdout.strip()
    return head if result.returncode == 0 and head else None


class RepositoryIntelligenceProvider:
    """Satisfies `repository-intelligence.v1` for a single repository root."""

    schema = "repository-intelligence.v1"
    provider_name = "code-review-graph"

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "provider": self.provider_name,
            "trust_states": [STATUS_CURRENT, STATUS_REFRESHED, STATUS_DEGRADED, STATUS_UNAVAILABLE],
            "supports_refresh": True,
            "supports_objective_search": True,
        }

    def health(self) -> dict[str, Any]:
        try:
            snapshot = inspect_graph(self.root)
            snapshot.store.close()
            return {"healthy": True, "detail": None}
        except Exception as exc:
            return {"healthy": False, "detail": f"{type(exc).__name__}: {exc}"}

    def status(self) -> dict[str, Any]:
        """Cheap trust-state check; does not run objective-scoped retrieval."""
        return self._build_payload(objective=None, allow_refresh=False, include_context=False)

    def refresh(self) -> dict[str, Any]:
        """Force a graph refresh, then report the resulting trust state."""
        return self._build_payload(objective=None, allow_refresh=True, include_context=False)

    def collect_context(self, objective: str | None = None) -> dict[str, Any]:
        """Full `repository-intelligence.v1` payload, including bounded context."""
        return self._build_payload(objective=objective, allow_refresh=True, include_context=True)

    def _build_payload(
        self, *, objective: str | None, allow_refresh: bool, include_context: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "status": STATUS_UNAVAILABLE,
            "provider": self.provider_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "indexed_revision": None,
            "trusted": False,
            "relevant_files": [],
            "relevant_symbols": [],
            "notes": [],
            "freshness_evidence": [],
        }
        snapshot: GraphSnapshot | None = None
        try:
            snapshot = inspect_graph(self.root)
            status = STATUS_CURRENT
            indexed_head = snapshot.metadata.get("git_head_sha") or None
            current_head = _current_git_head(self.root)
            if indexed_head and current_head and indexed_head != current_head:
                status = STATUS_DEGRADED
                payload["notes"].append(
                    "Indexed graph revision differs from current repository HEAD; graph-derived context withheld."
                )
            if snapshot.mismatches:
                if allow_refresh:
                    try:
                        refresh_graph(snapshot)
                        snapshot = inspect_graph(self.root)
                        status = STATUS_REFRESHED if not snapshot.mismatches else STATUS_DEGRADED
                    except Exception as exc:
                        status = STATUS_DEGRADED
                        payload["notes"].append(
                            f"Graph refresh failed; graph-derived context withheld: {type(exc).__name__}: {exc}"
                        )
                else:
                    status = STATUS_DEGRADED

            if include_context and status in TRUSTED_STATUSES:
                try:
                    context = bound_context(retrieve_context(self.root, objective))
                    payload["relevant_files"] = context.get("relevant_files", [])
                    payload["relevant_symbols"] = context.get("relevant_symbols", [])
                    payload["notes"].extend(context.get("notes", []))
                except Exception as exc:
                    status = STATUS_DEGRADED
                    payload["notes"].append(
                        f"Graph retrieval failed; graph-derived context withheld: {type(exc).__name__}: {exc}"
                    )
            elif status not in TRUSTED_STATUSES and not payload["notes"]:
                payload["notes"].append(
                    "Graph freshness could not be established; graph-derived context withheld."
                )

            payload["status"] = status
            payload["trusted"] = status in TRUSTED_STATUSES
            payload["indexed_revision"] = snapshot.metadata.get("git_head_sha") or None
            payload["freshness_evidence"] = _freshness_evidence(snapshot)
        except Exception as exc:
            payload["status"] = STATUS_UNAVAILABLE
            payload["trusted"] = False
            payload["notes"] = [f"Graph tooling unavailable: {type(exc).__name__}: {exc}"]
        finally:
            if snapshot is not None:
                snapshot.store.close()
        return payload
