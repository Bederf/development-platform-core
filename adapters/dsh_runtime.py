"""Thin DeepSeek Harness execution adapter.

The adapter owns process-scoped state and provider translation. Platform
identity remains in :mod:`adapters.agent_runtime` and credentials are supplied
by an external resolver; this module never persists or projects secret values.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import signal
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .agent_runtime import AgentExecutionIdentity, AgentRuntimeIdentityBridge, AgentRuntimeIdentityError


class DshRuntimeError(RuntimeError):
    """Raised when DSH cannot be launched with a valid execution boundary."""


CredentialResolver = Callable[[], Mapping[str, str]]
CommandBuilder = Callable[[str, Mapping[str, str] | None], Sequence[str]]
ArtifactCollector = Callable[[Path, AgentExecutionIdentity, "DshExecutionRecord"], Sequence[Mapping[str, Any]]]
ResultSink = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class DshExecutionRecord:
    """Non-secret record of one DSH process execution."""

    provider: str
    model: str | None
    identity: AgentExecutionIdentity
    provider_session_id: str | None
    returncode: int
    status: str


class DshRuntimeAdapter:
    """Run one DSH attempt inside disposable, credential-scoped state."""

    def __init__(
        self,
        *,
        runtime_root: str | Path,
        executable: str | Path,
        credential_resolver: CredentialResolver,
        allowed_credentials: Sequence[str] | None = None,
    ) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        self.executable = Path(executable).resolve()
        self.credential_resolver = credential_resolver
        self.allowed_credentials = frozenset(allowed_credentials or ("DEEPSEEK_API_KEY",))

    def execute(
        self,
        identity: AgentExecutionIdentity,
        *,
        args: Sequence[str],
        cwd: str | Path,
        model: str | None = None,
        provider: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> DshExecutionRecord:
        """Execute one attempt and return provider metadata without secrets."""

        if not self.executable.is_file():
            raise DshRuntimeError("dsh executable is unavailable")
        if not self.runtime_root.is_dir():
            raise DshRuntimeError("dsh runtime root is unavailable")
        credentials = dict(self.credential_resolver())
        if not credentials or not set(credentials).issubset(self.allowed_credentials):
            raise DshRuntimeError("credential resolver returned an unapproved credential")
        if any(not value for value in credentials.values()):
            raise DshRuntimeError("credential resolver returned an empty credential")

        bridge = AgentRuntimeIdentityBridge(identity, provider="dsh")
        try:
            with tempfile.TemporaryDirectory(
                prefix=f"attempt-{identity.attempt_id}-",
                dir=self.runtime_root,
            ) as dsh_home:
                os.chmod(dsh_home, 0o700)
                if provider and model:
                    self._write_model_settings(dsh_home, provider, model)
                environment = {
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": os.environ.get("HOME", str(Path.home())),
                    "DSH_HOME": dsh_home,
                    "DSH_TELEMETRY_DISABLED": "1",
                    **credentials,
                }
                process = subprocess.Popen(
                    [str(self.executable), *args],
                    cwd=str(Path(cwd).resolve()),
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                cancelled = False
                while True:
                    if process.poll() is not None:
                        break
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        os.killpg(process.pid, signal.SIGTERM)
                        break
                    try:
                        process.wait(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                process.communicate()
                session_id = self._session_id_optional(dsh_home)
                if session_id is not None:
                    bridge.bind_session(session_id)
                status = "cancelled" if cancelled else "succeeded" if process.returncode == 0 else "failed"
                if session_id is None and not cancelled:
                    raise DshRuntimeError("dsh execution did not produce a session record")
                return DshExecutionRecord(
                    provider="dsh",
                    model=model,
                    identity=identity,
                    provider_session_id=session_id,
                    returncode=process.returncode,
                    status=status,
                )
        except (OSError, subprocess.SubprocessError, AgentRuntimeIdentityError) as exc:
            raise DshRuntimeError("dsh execution failed") from exc
        finally:
            credentials.clear()
            if "environment" in locals():
                environment.clear()

    @staticmethod
    def _write_model_settings(dsh_home: str, provider: str, model: str) -> None:
        """Write only non-secret DSH model routing into disposable state."""

        provider_key = provider.lower()
        api_env = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }.get(provider_key)
        lines = ["agent-default-model:", f"  provider: {provider}", f"  model: {model}"]
        if api_env and provider_key != "deepseek":
            lines.extend(["llm-pi-ai:", "  providers:", f"    {provider}:", f"      apiKeyEnv: {api_env}"])
        Path(dsh_home, "settings.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _session_id_optional(dsh_home: str) -> str | None:
        sessions = sorted(Path(dsh_home).glob("sessions/*/session-*/session.jsonl.zstd"))
        if len(sessions) != 1:
            return None
        try:
            decoded = subprocess.run(
                ["zstd", "-dc", str(sessions[0])],
                capture_output=True,
                check=True,
            ).stdout
            session = json.loads(decoded.splitlines()[0])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None
        session_id = session.get("id")
        return session_id if isinstance(session_id, str) and session_id else None

    @classmethod
    def _session_id(cls, dsh_home: str) -> str:
        session_id = cls._session_id_optional(dsh_home)
        if session_id is None:
            raise DshRuntimeError("dsh session record is missing or invalid")
        return session_id


class DshAgentRuntimeAdapter:
    """Translate ``agent-runtime.v1`` requests into one DSH attempt."""

    def __init__(
        self,
        runtime: DshRuntimeAdapter,
        *,
        command_builder: CommandBuilder | None = None,
        artifact_collector: ArtifactCollector | None = None,
    ) -> None:
        self.runtime = runtime
        self.command_builder = command_builder or (lambda objective, _model: ("--profile", "headless", objective))
        self.artifact_collector = artifact_collector or (lambda _cwd, _identity, _record: ())
        self._models: dict[str, dict[str, str]] = {}
        self._artifacts: dict[str, list[dict[str, Any]]] = {}
        self._cancellations: dict[str, threading.Event] = {}

    def handle(
        self,
        request: Mapping[str, Any],
        *,
        cwd: str | Path,
        result_sink: ResultSink | None = None,
    ) -> dict[str, Any]:
        """Handle one contract request and return its final result."""

        self._validate_request(request)
        operation = str(request["operation"])
        identity = self._identity(request)
        if operation == "start":
            return self._result(request, "ACCEPTED")
        if operation == "select_model":
            model = dict(request["model"])
            self._models[identity.attempt_id] = model
            return self._result(request, "ACCEPTED", selected_model=model)
        if operation == "retry":
            return self._result(
                request,
                "ACCEPTED",
                retry={
                    "parent_attempt_id": request["previous_attempt_id"],
                    "new_attempt_id": identity.attempt_id,
                },
            )
        if operation == "cancel":
            event = self._cancellations.get(identity.attempt_id)
            if event is not None:
                event.set()
            return self._result(
                request,
                "CANCEL_REQUESTED",
                cancellation={"requested": True, "completed": False, "reason": request["reason"]},
            )
        if operation == "collect_artifacts":
            artifacts = [dict(artifact, publication="PUBLISHED") for artifact in self._artifacts.get(identity.attempt_id, [])]
            return self._result(request, "SUCCEEDED", artifacts=artifacts)
        if operation == "observe_events":
            return self._result(request, "SUCCEEDED", events=[])
        if operation == "execute":
            return self._execute(request, identity, cwd=cwd, result_sink=result_sink)
        raise DshRuntimeError(f"unsupported runtime operation: {operation}")

    def _execute(
        self,
        request: Mapping[str, Any],
        identity: AgentExecutionIdentity,
        *,
        cwd: str | Path,
        result_sink: ResultSink | None,
    ) -> dict[str, Any]:
        model = self._models.get(identity.attempt_id)
        if model is None and isinstance(request.get("model"), Mapping):
            model = dict(request["model"])
        cancel_event = threading.Event()
        self._cancellations[identity.attempt_id] = cancel_event
        if model is None:
            model = {"provider": "unselected", "model": "unselected"}
        running = self._result(
            request,
            "RUNNING",
            selected_model=model,
            events=[self._event("execution_started", 0)],
        )
        if result_sink is not None:
            result_sink(running)
        try:
            record = self.runtime.execute(
                identity,
                args=self.command_builder(str(request["task"]["objective"]), model),
                cwd=cwd,
                model=model["model"],
                provider=model["provider"],
                cancel_event=cancel_event,
            )
            artifacts = [
                dict(artifact, publication="PRODUCED")
                for artifact in self.artifact_collector(Path(cwd), identity, record)
            ]
            self._artifacts[identity.attempt_id] = artifacts
            status = "CANCELLED" if record.status == "cancelled" else "SUCCEEDED" if record.status == "succeeded" else "FAILED"
            fields: dict[str, Any] = {
                "selected_model": model,
                "events": [
                    self._event(
                        "execution_completed"
                        if status == "SUCCEEDED"
                        else "execution_cancelled"
                        if status == "CANCELLED"
                        else "execution_failed",
                        1,
                    )
                ],
                "artifacts": artifacts,
            }
            if record.provider_session_id:
                fields["provider_session"] = {"provider": record.provider, "session_id": record.provider_session_id}
            if status == "CANCELLED":
                fields["cancellation"] = {"requested": True, "completed": True, "reason": "runtime cancellation"}
            if status == "FAILED":
                fields["error"] = {"code": "DSH_EXECUTION_FAILED", "message": "DSH execution failed", "retryable": False}
            result = self._result(request, status, **fields)
            if result_sink is not None:
                result_sink(result)
            return result
        finally:
            self._cancellations.pop(identity.attempt_id, None)

    @staticmethod
    def _event(event_type: str, sequence: int) -> dict[str, Any]:
        return {
            "event_id": f"dsh-{sequence}-{event_type}",
            "event_type": event_type,
            "sequence": sequence,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _identity(request: Mapping[str, Any]) -> AgentExecutionIdentity:
        return AgentExecutionIdentity(**dict(request["execution"]))

    @staticmethod
    def _validate_request(request: Mapping[str, Any]) -> None:
        if request.get("schema") != "agent-runtime.v1" or request.get("message_type") != "request":
            raise DshRuntimeError("request is not an agent-runtime.v1 request")
        if not isinstance(request.get("request_id"), str) or not request["request_id"]:
            raise DshRuntimeError("request_id is required")
        if not isinstance(request.get("execution"), Mapping):
            raise DshRuntimeError("execution identity is required")
        if request.get("operation") == "execute" and not isinstance(request.get("task"), Mapping):
            raise DshRuntimeError("execute requires task")

    @staticmethod
    def _result(request: Mapping[str, Any], status: str, **fields: Any) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": "agent-runtime.v1",
            "message_type": "result",
            "operation": request["operation"],
            "request_id": f"result-for-{request['request_id']}",
            "in_reply_to": request["request_id"],
            "execution": dict(request["execution"]),
            "status": status,
        }
        result.update(fields)
        return result
