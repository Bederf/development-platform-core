"""Fail-closed, policy-bound process dispatch for platform startup."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .radix import StartupResolution


class StartupLaunchError(ValueError):
    """Raised when a startup resolution or launch request is not authorized."""


@dataclass(frozen=True)
class LaunchRequest:
    agent: str
    executable: str
    args: tuple[str, ...] = ()
    cwd: Path | str = "."
    env: Mapping[str, str] | None = None
    mounts: tuple[str, ...] = ()
    runtime: str | None = None
    network: str | None = None


@dataclass(frozen=True)
class PlatformLaunchPolicy:
    executable_by_agent: Mapping[str, Path]
    allowed_args: Mapping[str, set[tuple[str, ...]]]
    allowed_environment: frozenset[str] = frozenset()
    allowed_working_roots: tuple[Path, ...] = ()
    allowed_runtimes: frozenset[str] = frozenset()
    allowed_mounts: frozenset[str] = frozenset()
    allowed_networks: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "executable_by_agent",
            {agent: Path(executable).resolve() for agent, executable in self.executable_by_agent.items()},
        )
        object.__setattr__(self, "allowed_working_roots", tuple(Path(root).resolve() for root in self.allowed_working_roots))


@dataclass(frozen=True)
class LaunchResult:
    returncode: int
    stdout: str
    stderr: str
    provenance: dict[str, object]


class PlatformLauncher:
    """Dispatch only commands explicitly authorized by platform policy."""

    def __init__(self, policy: PlatformLaunchPolicy) -> None:
        self.policy = policy

    def launch(self, resolution: StartupResolution, request: LaunchRequest) -> LaunchResult:
        self._validate_resolution(resolution)
        executable = self._validate_request(request, resolution)
        environment = dict(request.env or {})
        completed = subprocess.run(
            [str(executable), *request.args],
            cwd=str(Path(request.cwd).resolve()),
            env=environment,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
        )
        return LaunchResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            provenance={
                "agent": request.agent,
                "executable": str(executable),
                "args": list(request.args),
                "cwd": str(Path(request.cwd).resolve()),
                "environment_keys": sorted(environment),
                "shell": False,
                "runtime": request.runtime,
                "mounts": list(request.mounts),
                "network": request.network,
                "resolution": resolution.provenance,
            },
        )

    @staticmethod
    def _validate_resolution(resolution: StartupResolution) -> None:
        if not resolution.ready or not resolution.execution_allowed:
            raise StartupLaunchError("startup resolution is not executable")
        if resolution.context is None:
            raise StartupLaunchError("ready resolution has no startup context")

    def _validate_request(self, request: LaunchRequest, resolution: StartupResolution) -> Path:
        expected = self.policy.executable_by_agent.get(request.agent)
        if expected is None:
            raise StartupLaunchError("agent is not platform-authorized")
        agents = resolution.context.get("agents", {})
        if not isinstance(agents, dict) or agents.get(request.agent) is not True:
            raise StartupLaunchError("agent is not enabled")
        executable = Path(request.executable).resolve()
        if executable != expected:
            raise StartupLaunchError("executable is not platform-authorized")
        if tuple(request.args) not in self.policy.allowed_args.get(request.agent, set()):
            raise StartupLaunchError("arguments are not platform-authorized")
        if request.env is not None and not set(request.env).issubset(self.policy.allowed_environment):
            raise StartupLaunchError("environment contains unapproved keys")
        if request.mounts and not set(request.mounts).issubset(self.policy.allowed_mounts):
            raise StartupLaunchError("mounts are not platform-authorized")
        if request.runtime is not None and request.runtime not in self.policy.allowed_runtimes:
            raise StartupLaunchError("runtime is not platform-authorized")
        if request.network is not None and request.network not in self.policy.allowed_networks:
            raise StartupLaunchError("network mode is not platform-authorized")
        cwd = Path(request.cwd).resolve()
        if not cwd.is_dir() or not any(self._is_within(cwd, root) for root in self.policy.allowed_working_roots):
            raise StartupLaunchError("working directory is not platform-authorized")
        context_root = resolution.context.get("repository_root")
        if not isinstance(context_root, str) or not context_root.strip():
            raise StartupLaunchError("startup context has no authoritative repository root")
        try:
            authoritative_root = Path(context_root).expanduser().resolve(strict=True)
        except OSError as exc:
            raise StartupLaunchError("startup context repository root is unavailable") from exc
        if cwd != authoritative_root:
            raise StartupLaunchError(
                "launch working directory does not match startup context repository root"
            )
        return executable

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True
