"""Real temporary Git repositories and fake reviewers exercise generated hooks."""

import io
import json
import os
import subprocess
import sys

import pytest

from adapters.radix.cli import main


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    return root


def initialize(root, capabilities=("gsd",), extra=(), apply_extra=()):
    plan = root / "plan.json"
    argv = [
        "init",
        "--project",
        str(root),
        "--project-id",
        "fixture",
        "--output",
        str(plan),
        "--overwrite",
    ]
    for cap in capabilities:
        argv += ["--capability", cap]
    out = io.StringIO()
    assert main([*argv, *extra], stdout=out, stdin=io.StringIO("\n")) == 0, (
        out.getvalue()
    )
    out = io.StringIO()
    rc = main(
        [
            "init",
            "--project",
            str(root),
            "--apply",
            str(plan),
            "--approve",
            "--guided",
            "--task",
            "Verify project",
            *apply_extra,
        ],
        stdout=out,
        stdin=io.StringIO(""),
    )
    return rc, out.getvalue()


def hook(root, name, data="", **extra_env):
    env = dict(os.environ, **extra_env)
    env.pop("SKIP_OPEN_CODE_REVIEW", None)
    return subprocess.run(
        ["bash", str(root / ".githooks" / name)],
        cwd=root,
        env=env,
        input=data,
        capture_output=True,
        text=True,
    )


def commit(root, name, content):
    (root / name).write_text(content)
    git(root, "add", name)
    git(root, "-c", "core.hooksPath=/dev/null", "commit", "-qm", name)
    return git(root, "rev-parse", "HEAD")


def test_task_path_cannot_escape(project):
    rc, _ = initialize(
        project, apply_extra=("--task-authority", str(project) + "/../outside.md")
    )
    assert rc == 2
    assert not (project.parent / "outside.md").exists()
    assert not (project / "development-platform.yaml").exists()


def test_symlink_task_path_cannot_escape(project):
    outside = project.parent / "outside"
    outside.mkdir()
    (project / "link").symlink_to(outside, target_is_directory=True)
    rc, _ = initialize(
        project, apply_extra=("--task-authority", str(project / "link" / "task.md"))
    )
    assert rc == 2
    assert not (outside / "task.md").exists()


def test_existing_hook_directory_preserved(project):
    git(project, "config", "core.hooksPath", ".custom-hooks")
    rc, _ = initialize(project)
    assert rc == 2
    assert git(project, "config", "core.hooksPath") == ".custom-hooks"
    assert not (project / "development-platform.yaml").exists()


def test_default_existing_hook_preserved(project):
    old = project / ".git/hooks/pre-commit"
    old.write_text("#!/bin/sh\nexit 1\n")
    old.chmod(0o755)
    assert initialize(project)[0] == 2
    assert (
        subprocess.run(
            ["git", "-C", str(project), "config", "--get", "core.hooksPath"]
        ).returncode
        == 1
    )


def test_staged_json_checked_not_working_copy(project):
    assert initialize(project)[0] == 0
    (project / "test.json").write_text("{broken\n")
    git(project, "add", "test.json")
    (project / "test.json").write_text("{}\n")
    assert hook(project, "pre-commit").returncode != 0


def test_first_push_checks_root_commit(project):
    assert initialize(project)[0] == 0
    tip = commit(project, "test.json", "{broken\n")
    run = hook(
        project, "pre-push", f"refs/heads/main {tip} refs/heads/main {'0' * 40}\n"
    )
    assert run.returncode != 0
    assert "JSON" in run.stdout + run.stderr


def test_push_checks_each_ref(project):
    assert initialize(project)[0] == 0
    base = commit(project, "base.txt", "base\n")
    bad = commit(project, "bad.json", "{broken\n")
    git(project, "checkout", "-q", "--detach", base)
    good = commit(project, "good.json", "{}\n")
    data = f"refs/heads/bad {bad} refs/heads/bad {base}\nrefs/heads/good {good} refs/heads/good {base}\n"
    assert hook(project, "pre-push", data).returncode != 0


def test_invalid_push_range_fails_closed(project):
    assert initialize(project)[0] == 0
    data = f"refs/heads/main {'1' * 40} refs/heads/main {'2' * 40}\n"
    assert hook(project, "pre-push", data).returncode != 0


def test_reviews_only_on_push_and_use_outgoing_snapshot(project, tmp_path):
    assert initialize(project, ("gsd", "ocr"))[0] == 0
    stub = tmp_path / "reviewer.py"
    log = tmp_path / "review.json"
    stub.write_text(
        'import json,os,pathlib,sys\npathlib.Path(os.environ["REVIEW_LOG"]).write_text(json.dumps({p:pathlib.Path(p).read_text() for p in sys.argv[1:]}))\n'
    )
    env = {"OPEN_CODE_REVIEW_CMD": f"{sys.executable} {stub}", "REVIEW_LOG": str(log)}
    tip = commit(project, "code.py", "value = 1\n")
    (project / "code.py").write_text("value = 2\n")
    git(project, "add", "code.py")
    assert hook(project, "pre-commit", **env).returncode == 0
    assert not log.exists()
    run = hook(
        project,
        "pre-push",
        f"refs/heads/main {tip} refs/heads/main {'0' * 40}\n",
        **env,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(log.read_text())["code.py"] == "value = 1\n"


def test_reapply_updates_effective_review_selection(project):
    assert initialize(project)[0] == 0
    assert initialize(project, ("gsd", "ocr"), apply_extra=("--overwrite",))[0] == 0
    config = json.loads(
        (project / ".development-platform/quality-hooks.json").read_text()
    )
    assert config["ai_review"] is True
    assert config["transport"] == "direct"


def test_optional_transport_values_remain_data(project, tmp_path):
    marker = tmp_path / "unexpected"
    value = "prod$(touch${IFS}" + str(marker) + ")"
    extra = (
        "--ocr-transport",
        "omniroute",
        "--infisical-project-id",
        "c4e2e9f3-9ab5-4fe2-a74e-05052a097cb4",
        "--infisical-env",
        value,
    )
    assert initialize(project, ("gsd", "ocr"), extra=extra)[0] == 0
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "infisical"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    tip = commit(project, "code.py", "value = 1\n")
    run = hook(
        project,
        "pre-push",
        f"refs/heads/main {tip} refs/heads/main {'0' * 40}\n",
        PATH=str(bindir) + os.pathsep + os.environ["PATH"],
    )
    assert run.returncode == 0, run.stderr
    assert not marker.exists()


def test_intent_is_saved_and_eof_exits(project):
    assert (
        initialize(
            project,
            extra=(
                "--guided",
                "--intent",
                "Study energy",
                "--constraint",
                "No live writes",
            ),
        )[0]
        == 0
    )
    context = json.loads((project / "plan.json").read_text())["project_context"]
    assert context == {"intent": "Study energy", "constraints": ["No live writes"]}
    assert (
        main(
            ["init", "--guided", "--project", str(project)],
            stdout=io.StringIO(),
            stdin=io.StringIO(""),
        )
        == 2
    )


@pytest.mark.parametrize(
    "status,coverage,expected",
    [
        ("success", 1, 0),
        ("partial", 1, 1),
        ("success", 0, 1),
        ("success", True, 1),
        ("success", None, 1),
        ("success", "1", 1),
    ],
)
def test_default_core_reviewer_is_direct_and_bounded(
    project, tmp_path, status, coverage, expected
):
    assert initialize(project, ("gsd", "ocr"))[0] == 0
    binary = tmp_path / "fake-ocr"
    log = tmp_path / "ocr-args.json"
    binary.write_text(
        '#!/usr/bin/env python3\nimport json,os,pathlib,sys\npathlib.Path(os.environ["OCR_LOG"]).write_text(json.dumps(sys.argv[1:]))\nprint(json.dumps({"status":os.environ["FAKE_STATUS"],"summary":{"files_reviewed":json.loads(os.environ["FAKE_COVERAGE"])}}))\n'
    )
    binary.chmod(0o755)
    tip = commit(project, "code.py", "value = 1\n")
    run = hook(
        project,
        "pre-push",
        f"refs/heads/main {tip} refs/heads/main {'0' * 40}\n",
        OCR_BIN=str(binary),
        OCR_LOG=str(log),
        FAKE_STATUS=status,
        FAKE_COVERAGE=json.dumps(coverage),
    )
    assert run.returncode == expected, run.stderr
    argv = json.loads(log.read_text())
    assert argv[0] == "scan"
    assert argv[argv.index("--concurrency") + 1] == "1"


def test_real_local_push_is_blocked_on_invalid_content(project, tmp_path):
    assert initialize(project)[0] == 0
    commit(project, "broken.json", "{invalid\n")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    push = subprocess.run(
        ["git", "-C", str(project), "push", str(bare), "HEAD:refs/heads/main"],
        capture_output=True,
        text=True,
    )
    assert push.returncode != 0
    assert "JSON" in push.stdout + push.stderr
    assert (
        subprocess.run(
            ["git", "-C", str(bare), "rev-parse", "--verify", "refs/heads/main"],
            capture_output=True,
        ).returncode
        != 0
    )


def test_deleted_ref_skips_reviewer(project):
    assert initialize(project, ("gsd", "ocr"))[0] == 0
    run = hook(
        project,
        "pre-push",
        f"(delete) {'0' * 40} refs/heads/main {'1' * 40}\n",
        OPEN_CODE_REVIEW_CMD="/missing/reviewer",
    )
    assert run.returncode == 0
