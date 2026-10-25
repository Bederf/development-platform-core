"""Evidence-capturing DSH-TUI provider for independent code review.

The adapter deliberately treats the TUI as an external reviewer process.  It
does not grant authority, edits the reviewed repository, or infer a review
result from process completion.  The complete terminal exchange is persisted
through the existing review evidence store before the result is returned.
"""

from __future__ import annotations

import json
import os
import pty
import re
import select
import signal
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from .code_review_provider import CodeReviewProviderError, require_exact_disposition
from .review_evidence import ReviewEvidenceStore


class DshTuiCodeReviewProvider:
    """Run one fresh DSH-TUI review and retain its raw terminal evidence."""

    def __init__(self, *, command: str = "dsh-tui", timeout_seconds: int = 600) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.model = os.environ.get("DSH_TUI_REVIEW_MODEL", "operator_selected")
        self.last_observation: dict[str, Any] | None = None

    @classmethod
    def from_environment(cls) -> "DshTuiCodeReviewProvider":
        return cls(
            command=os.environ.get("DSH_TUI_COMMAND", "dsh-tui"),
            timeout_seconds=int(os.environ.get("DSH_TUI_REVIEW_TIMEOUT_SECONDS", "600")),
        )

    def __call__(self, package: Mapping[str, Any]) -> Mapping[str, Any]:
        runtime = package.get("_runtime") if isinstance(package.get("_runtime"), Mapping) else {}
        request_id = str(runtime.get("provider_request_id") or f"dsh-tui-request-{uuid4().hex}")
        self.last_observation = {
            "provider": "dsh-tui",
            "model": self.model,
            "gsd_request_id": str(runtime.get("gsd_request_id") or "unknown"),
            "provider_request_id": request_id,
            "omniroute_call_id": None,
            "generation_id": None,
            "fresh_request": True,
            "cache_status": "NOT_APPLICABLE",
            "response_format": {"type": "json", "markers": True},
            "schema_version": "code-review-result.v1",
            "raw_provider_status": "NOT_RECEIVED",
            "raw_provider_response": None,
            "failure_classification": None,
        }
        prompt = self._prompt(package)
        raw_terminal = self._run(prompt)
        session_text = self._session_text(raw_terminal)
        raw = raw_terminal
        if session_text:
            raw += "\n--- DSH SESSION TEXT ---\n" + session_text
        self.last_observation["raw_provider_status"] = "RECEIVED"
        self.last_observation["raw_provider_response"] = raw

        evidence_root = str(os.environ.get("GSD_REVIEW_EVIDENCE_ROOT", "")).strip()
        if evidence_root:
            evidence = ReviewEvidenceStore(
                evidence_root,
                retention_days=int(os.environ.get("GSD_REVIEW_EVIDENCE_RETENTION_DAYS", "30")),
            ).persist(self.last_observation)
            self.last_observation.update(evidence)

        result = self._parse_result(session_text or raw)
        result["attempt_ref"] = str(package["attempt_ref"])
        result["independence"] = "independent"
        result["providers"] = {
            "considered": ["dsh-tui"],
            "selected": [self.model],
            "skipped": [],
        }
        requested = list(runtime.get("evidence_refs") or [])
        result["evidence"] = [{"kind": "review-package", "ref": str(ref)} for ref in requested]
        if len(result["evidence"]) < 3:
            raise CodeReviewProviderError("DSH-TUI review request did not contain three evidence references")
        return result

    @staticmethod
    def _prompt(package: Mapping[str, Any]) -> str:
        return (
            "You are an independent read-only assurance reviewer. Review only the supplied bounded package. "
            "Do not use tools, modify files, or claim commands were run. Return exactly one JSON object "
            "matching code-review-result.v1 between the literal markers REVIEW_JSON_BEGIN and "
            "REVIEW_JSON_END. The object must include schema, review_id, attempt_ref, independence, "
            "classification, providers, findings, disposition, evidence, and generated_at. "
            "Use only PASS, PASS_WITH_ADVISORIES, CHANGES_REQUIRED, INCOMPLETE_REVIEW, or BLOCKED. "
            "For every finding, cite only a supplied evidence reference or changed-file reference.\n\n"
            "BOUNDED REVIEW PACKAGE:\n"
            + json.dumps(dict(package), sort_keys=True)
            + "\n\nFINAL OUTPUT ONLY."
        )

    def _run(self, prompt: str) -> str:
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe(self.command, [self.command], {**os.environ, "DSH_PROFILE": "tui"})
        chunks: list[bytes] = []
        start = time.monotonic()
        sent = False
        try:
            while time.monotonic() - start < self.timeout_seconds:
                ready, _, _ = select.select([fd], [], [], 0.25)
                if ready:
                    try:
                        chunks.append(os.read(fd, 65536))
                    except OSError:
                        break
                if not sent and time.monotonic() - start >= 1.5:
                    os.write(fd, prompt.encode("utf-8") + b"\r")
                    sent = True
                text = b"".join(chunks).decode("utf-8", errors="replace")
                # The TUI echoes and redraws the submitted prompt.  Those
                # redraws contain the literal marker too; require a third end
                # marker so at least one marker belongs to the model turn.
                if text.count("REVIEW_JSON_END") >= 3:
                    return text
            raise CodeReviewProviderError("DSH-TUI review timed out before a complete result")
        finally:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass

    @staticmethod
    def _session_text(raw_terminal: str) -> str:
        """Recover structured model text from DSH's durable session record."""

        matches = re.findall(r"main-session-[0-9a-f]{8}-[0-9a-f-]{27,}", raw_terminal)
        if not matches:
            return ""
        session_id = matches[-1]
        root = Path(os.environ.get("DSH_SESSION_ROOT", "~/.local/state/dsh/sessions")).expanduser()
        paths = list(root.glob(f"*/{session_id}/session.jsonl.zstd"))
        if not paths:
            return ""
        try:
            completed = subprocess.run(
                ["zstd", "-dc", str(paths[-1])],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        text_chunks: list[str] = []
        for line in completed.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "text-chunks":
                data = event.get("data")
                if isinstance(data, Mapping):
                    texts = data.get("texts")
                    if isinstance(texts, list):
                        text_chunks.extend(str(item) for item in texts)
        return "".join(text_chunks)

    @staticmethod
    def _parse_result(raw: str) -> dict[str, Any]:
        marked = list(re.finditer(r"REVIEW_JSON_BEGIN\s*(\{.*?\})\s*REVIEW_JSON_END", raw, re.DOTALL))
        candidate = marked[-1].group(1) if marked else ""
        if not candidate:
            clean = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))", "", raw)
            decoder = json.JSONDecoder()
            for match in re.finditer(r'\{"schema"\s*:\s*"code-review-result\.v1"', clean):
                try:
                    candidate, _ = decoder.raw_decode(clean[match.start():])
                    break
                except json.JSONDecodeError:
                    continue
        if not isinstance(candidate, (str, dict)):
            raise CodeReviewProviderError("DSH-TUI returned no marked review result")
        try:
            result = json.loads(candidate) if isinstance(candidate, str) else candidate
        except json.JSONDecodeError as exc:
            raise CodeReviewProviderError("DSH-TUI returned invalid review JSON") from exc
        if not isinstance(result, dict):
            raise CodeReviewProviderError("DSH-TUI review result is not an object")
        require_exact_disposition(result, provider="DSH-TUI")
        return result
