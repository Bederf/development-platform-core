"""Provider-neutral construction of ``forge-adapter.v1`` requests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


class ForgeRequestError(ValueError):
    """Raised when a Forge operation request is incomplete or invalid."""


class ForgeRequestAdapter:
    """Build typed Forge lifecycle requests without executing Forge."""

    _OPERATIONS = frozenset({"start", "verify", "finish"})

    def build(
        self,
        *,
        operation: str,
        project_id: str,
        request_id: str,
        session_id: str | None = None,
        verification_request: Mapping[str, Any] | None = None,
        closeout_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if operation not in self._OPERATIONS:
            raise ForgeRequestError(f"unsupported Forge operation: {operation!r}")
        for value, name in ((project_id, "project_id"), (request_id, "request_id")):
            if not isinstance(value, str) or not value.strip():
                raise ForgeRequestError(f"{name} must be a non-empty string")
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise ForgeRequestError("session_id must be null or a non-empty string")
        if verification_request is not None and not isinstance(verification_request, Mapping):
            raise ForgeRequestError("verification_request must be an object or null")
        if closeout_context is not None and not isinstance(closeout_context, Mapping):
            raise ForgeRequestError("closeout_context must be an object or null")
        return {
            "schema": "forge-adapter.v1",
            "operation": operation,
            "project_id": project_id,
            "request_id": request_id,
            "session_id": session_id,
            "verification_request": deepcopy(dict(verification_request)) if verification_request is not None else None,
            "closeout_context": deepcopy(dict(closeout_context)) if closeout_context is not None else None,
        }
