"""Supervise a Forge process without granting it Core authority."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Sequence


@dataclass(frozen=True)
class ForgeProcessObservation:
    """Operational output produced when Forge exits or is interrupted."""

    provider_status: str
    returncode: int | None
    stdout: str
    stderr: str
    termination_signal: int | None = None
    termination_reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_status": self.provider_status,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "termination_signal": self.termination_signal,
            "termination_reason": self.termination_reason,
        }


class ForgeProcessSupervisor:
    """Run Forge in an isolated process group and fail closed on termination."""

    def run(
        self,
        command: Sequence[str],
        *,
        repository: Path,
        timeout_seconds: float,
        cancel_event: Event | None = None,
    ) -> ForgeProcessObservation:
        if not command:
            raise ValueError("Forge command is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        process = subprocess.Popen(
            list(command),
            cwd=repository,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        started = time.monotonic()
        termination_signal: int | None = None
        termination_reason: str | None = None
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                termination_signal = signal.SIGTERM
                termination_reason = "operator cancellation"
                self._terminate(process, termination_signal)
                break
            if time.monotonic() - started >= timeout_seconds:
                termination_signal = signal.SIGTERM
                termination_reason = "supervisor timeout"
                self._terminate(process, termination_signal)
                break
            time.sleep(0.01)

        stdout, stderr = process.communicate()
        if termination_reason == "operator cancellation":
            status = "CANCELLED"
        elif termination_reason == "supervisor timeout":
            status = "TIMEOUT"
        else:
            status = "PASS" if process.returncode == 0 else "FAIL"
        return ForgeProcessObservation(
            provider_status=status,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
            termination_signal=termination_signal,
            termination_reason=termination_reason,
        )

    @staticmethod
    def _terminate(process: subprocess.Popen[str], termination_signal: int) -> None:
        try:
            os.killpg(process.pid, termination_signal)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
