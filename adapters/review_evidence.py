"""Access-controlled, content-addressed storage for review transport evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


class ReviewEvidenceError(ValueError):
    """Raised when review evidence cannot be safely retained."""


class ReviewEvidenceStore:
    """Persist redacted provider responses with a bounded retention date."""

    def __init__(self, root: str | Path, *, retention_days: int = 30) -> None:
        if retention_days < 1 or retention_days > 3650:
            raise ReviewEvidenceError("retention_days must be between 1 and 3650")
        self.root = Path(root).expanduser().resolve()
        self.retention_days = retention_days

    def persist(self, observation: Mapping[str, Any]) -> dict[str, str]:
        raw = observation.get("raw_provider_response")
        request_id = str(observation.get("provider_request_id") or "").strip()
        if not isinstance(raw, str) or not raw:
            raise ReviewEvidenceError("raw provider response is required")
        if not request_id or not re.fullmatch(r"[A-Za-z0-9._-]+", request_id):
            raise ReviewEvidenceError("provider request ID is required and must be path-safe")
        redacted = _redact(raw)
        digest = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.root.chmod(0o700)
        except OSError as exc:
            raise ReviewEvidenceError(f"could not secure review evidence root: {exc}") from exc
        evidence_dir = self.root / request_id
        response_path = evidence_dir / "raw-response.txt"
        manifest_path = evidence_dir / "manifest.json"
        if evidence_dir.exists():
            raise ReviewEvidenceError("review evidence already exists; refusing overwrite")
        try:
            evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            response_path.write_text(redacted, encoding="utf-8", newline="")
            response_path.chmod(0o600)
            manifest = {
                "schema": "review-transport-evidence.v1",
                "provider_request_id": request_id,
                "provider": str(observation.get("provider") or "unknown"),
                "model": str(observation.get("model") or "unknown"),
                "gsd_request_id": str(observation.get("gsd_request_id") or "unknown"),
                "omniroute_call_id": observation.get("omniroute_call_id"),
                "generation_id": observation.get("generation_id"),
                "raw_provider_status": observation.get("raw_provider_status"),
                "cache_status": str(observation.get("cache_status") or "UNKNOWN"),
                "fresh_request": bool(observation.get("fresh_request")),
                "response_format": observation.get("response_format"),
                "schema_version": observation.get("schema_version"),
                "raw_response_sha256": f"sha256:{digest}",
                "raw_response_ref": response_path.relative_to(self.root).as_posix(),
                "retention_until": (date.today() + timedelta(days=self.retention_days)).isoformat(),
                "created_at": datetime.now(UTC).isoformat(),
            }
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            manifest_path.chmod(0o600)
        except OSError as exc:
            raise ReviewEvidenceError(f"could not persist review evidence: {exc}") from exc
        return {
            "raw_response_ref": str(response_path),
            "raw_response_digest": f"sha256:{digest}",
            "retention_until": manifest["retention_until"],
        }


def _redact(raw: str) -> str:
    """Remove common credential forms before evidence leaves process memory."""

    redacted = re.sub(
        r"(?i)(authorization\s*[\"']?\s*[:=]\s*[\"']?\s*bearer\s+)[^\s,}\"]+",
        r"\1[REDACTED]",
        raw,
    )
    redacted = re.sub(
        r"(?i)(api[_-]?key\s*[\"']?\s*[:=]\s*[\"']?\s*)[^\s,}\"]+",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted
