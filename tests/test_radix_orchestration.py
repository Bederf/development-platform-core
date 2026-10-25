from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from adapters.radix.orchestration import (
    OrcaOrchestrationClient,
    OrcaOrchestrationError,
    OrchestrationDispatch,
)
from adapters.radix.cli import main as radix_main

from tests.test_radix_cli import write_project


class FakeOrca:
    def __init__(self, responses: list[dict], *, returncode: int = 0) -> None:
        self.responses = iter(responses)
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        response = next(self.responses)
        return subprocess.CompletedProcess(argv, self.returncode, json.dumps(response), "")


def test_dispatch_uses_bounded_run_task_worker_argv_and_evidence(tmp_path: Path) -> None:
    runner = FakeOrca([
        {"status": "ready", "run": {"id": "run_123"}},
        {"status": "created", "task": {"id": "task_123"}},
        {"status": "ready", "dispatch": {"dispatch_id": "dispatch_123"}},
    ])
    evidence = tmp_path / ".runtime" / "dispatch.json"
    result = OrcaOrchestrationClient(runner=runner).dispatch(
        project_id="development-platform-core",
        repository_root=tmp_path,
        session_id="radix-session",
        agent="codex",
        objective="Bounded objective",
        task_spec="Implement the bounded task",
        task_title="Core worker",
        evidence_path=evidence,
        environment={"PATH": "/safe"},
    )

    assert result == OrchestrationDispatch(
        run_id="run_123",
        task_id="task_123",
        worker_id="dispatch_123",
        evidence_path=evidence,
        statuses={"run": "ready", "task": "created", "worker": "ready"},
    )
    assert [call[2] for call in runner.calls] == ["run-create", "task-create", "worker-start"]
    assert "--repo" in runner.calls[2]
    assert f"path:{tmp_path}" in runner.calls[2]
    record = json.loads(evidence.read_text(encoding="utf-8"))
    assert record["run_id"] == "run_123"
    assert record["task_id"] == "task_123"
    assert record["worker_id"] == "dispatch_123"
    assert record["commands"][0][-1] == "--json"
    assert oct(evidence.stat().st_mode & 0o777) == "0o600"


def test_dispatch_uses_domain_run_identity_not_transport_envelope_id(tmp_path: Path) -> None:
    runner = FakeOrca([
        {"id": "request-run", "ok": True, "result": {"run": {"id": "run_domain"}}},
        {"id": "request-task", "ok": True, "result": {"task": {"id": "task_domain"}}},
        {"id": "request-worker", "ok": True, "result": {"dispatch": {"dispatch_id": "dispatch_domain"}}},
    ])

    result = OrcaOrchestrationClient(runner=runner).dispatch(
        project_id="development-platform-core",
        repository_root=tmp_path,
        session_id="radix-session",
        agent="codex",
        objective="Identity reconciliation",
        task_spec="Use the domain identity",
        task_title="Identity task",
        evidence_path=tmp_path / "dispatch.json",
    )

    assert result.run_id == "run_domain"
    assert result.task_id == "task_domain"
    assert result.worker_id == "dispatch_domain"
    assert "run_domain" in runner.calls[1]
    assert "request-run" not in runner.calls[1]


def test_existing_run_show_uses_domain_identity_not_transport_envelope_id(tmp_path: Path) -> None:
    runner = FakeOrca([
        {"id": "request-show", "ok": True, "result": {"run": {"id": "run_existing"}}},
        {"id": "request-task", "ok": True, "result": {"task": {"id": "task_existing"}}},
        {"id": "request-worker", "ok": True, "result": {"worker": {"id": "worker_existing"}}},
    ])

    result = OrcaOrchestrationClient(runner=runner).dispatch(
        project_id="development-platform-core",
        repository_root=tmp_path,
        session_id="radix-session",
        agent="codex",
        objective="Existing run identity",
        task_spec="Use the existing domain identity",
        task_title="Existing identity task",
        run_id="run_existing",
        evidence_path=tmp_path / "dispatch.json",
    )

    assert result.run_id == "run_existing"
    assert result.worker_id == "worker_existing"
    assert "--run" in runner.calls[1]
    assert runner.calls[1][runner.calls[1].index("--run") + 1] == "run_existing"


def test_transport_envelope_id_without_domain_identity_fails_closed(tmp_path: Path) -> None:
    runner = FakeOrca([{"id": "request-only", "ok": True, "result": {}}])
    with pytest.raises(OrcaOrchestrationError, match="run identity is missing or unsafe"):
        OrcaOrchestrationClient(runner=runner).dispatch(
            project_id="development-platform-core",
            repository_root=tmp_path,
            session_id="radix-session",
            agent="codex",
            objective="Reject envelope identity",
            task_spec="Reject envelope identity",
            task_title="Reject envelope identity",
            evidence_path=tmp_path / "dispatch.json",
        )
    assert len(runner.calls) == 1


def test_existing_run_is_checked_and_reused(tmp_path: Path) -> None:
    runner = FakeOrca([
        {"status": "ready", "run": {"id": "run_existing"}},
        {"status": "created", "task": {"id": "task_existing"}},
        {"status": "ready", "dispatch": {"dispatch_id": "dispatch_existing"}},
    ])
    result = OrcaOrchestrationClient(runner=runner).dispatch(
        project_id="development-platform-core",
        repository_root=tmp_path,
        session_id="radix-session",
        agent="codex",
        objective="Existing run objective",
        task_spec="Existing run task",
        task_title="Existing task",
        run_id="run_existing",
        evidence_path=tmp_path / "dispatch.json",
    )

    assert result.run_id == "run_existing"
    assert runner.calls[0][2:5] == ["run-show", "--id", "run_existing"]
    assert "--run" in runner.calls[1]


@pytest.mark.parametrize(
    "responses, expected",
    [
        ([{"status": "ready"}], "run identity is missing or unsafe"),
        ([{"status": "ready", "run": {"id": "run_ok"}}, {"status": "created"}], "task identity is missing or unsafe"),
    ],
)
def test_missing_controller_identity_fails_closed(tmp_path: Path, responses: list[dict], expected: str) -> None:
    runner = FakeOrca(responses)
    with pytest.raises(OrcaOrchestrationError, match=expected):
        OrcaOrchestrationClient(runner=runner).dispatch(
            project_id="development-platform-core",
            repository_root=tmp_path,
            session_id="radix-session",
            agent="codex",
            objective="Objective",
            task_spec="Task",
            task_title="Title",
            evidence_path=tmp_path / "dispatch.json",
        )
    assert not (tmp_path / "dispatch.json").exists()


def test_cli_orchestrate_dispatches_without_invoking_direct_agent(tmp_path: Path, monkeypatch) -> None:
    write_project(tmp_path, project_id="development-platform-core")
    calls: list[object] = []

    def fake_dispatch(self, **kwargs):
        calls.append(kwargs)
        evidence = kwargs["evidence_path"]
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text("{}\n", encoding="utf-8")
        return OrchestrationDispatch(
            run_id="run_cli",
            task_id="task_cli",
            worker_id="dispatch_cli",
            evidence_path=evidence,
            statuses={"run": "ready", "task": "created", "worker": "ready"},
        )

    monkeypatch.setattr("adapters.radix.cli.OrcaOrchestrationClient.dispatch", fake_dispatch)
    result = radix_main(
        [
            "--project", str(tmp_path),
            "--session-id", "radix-cli",
            "--codex",
            "--orchestrate",
            "--orchestration-spec", "Run the bounded worker",
            "--orchestration-task-title", "CLI worker",
        ],
        environ={"PATH": "/safe/bin"},
        which=lambda name, path=None: "/safe/bin/codex",
        executor=lambda *args: (_ for _ in ()).throw(AssertionError("direct agent must not execute")),
        chdir=lambda path: None,
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0]["project_id"] == "development-platform-core"
    assert calls[0]["agent"] == "codex"
    assert calls[0]["task_spec"] == "Run the bounded worker"
