from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.launcher import (
    LaunchRequest,
    PlatformLaunchPolicy,
    PlatformLauncher,
    StartupLaunchError,
)
from adapters.radix import RadixStartupAdapter, StartupResolution


class PlatformLauncherTests(unittest.TestCase):
    def test_disposable_generic_consumer_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            consumer = Path(directory)
            (consumer / "vault").mkdir()
            (consumer / "00-GSD-Phases").mkdir()
            (consumer / "TODO.md").write_text(
                "- [ ] Run the generic consumer compatibility proof\n", encoding="utf-8"
            )
            declaration = consumer / "development-platform.yaml"
            declaration.write_text(
                "schema: development-platform.v1\n"
                "project:\n"
                "  id: disposable-generic-consumer\n"
                "  root: .\n"
                "  knowledge_root: vault\n"
                "  planning_root: 00-GSD-Phases\n"
                "repository_intelligence:\n"
                "  enabled: true\n"
                "  provider: code-review-graph\n"
                "  degraded_mode: startup-without-trusted-context\n"
                "agents:\n"
                "  codex: true\n"
                "gsd:\n"
                "  enabled: true\n"
                "  task_authority: TODO.md\n",
                encoding="utf-8",
            )
            script = consumer / "agent.py"
            evidence = consumer / "startup-evidence.txt"
            script.write_text(
                "import os\n"
                "from pathlib import Path\n"
                "Path(os.environ['EVIDENCE']).write_text('generic-consumer-started', encoding='utf-8')\n",
                encoding="utf-8",
            )

            resolution = RadixStartupAdapter(declaration).resolve_startup(
                session_id="generic-consumer-compatibility", agent="codex"
            )
            policy = PlatformLaunchPolicy(
                executable_by_agent={"codex": Path(sys.executable)},
                allowed_args={"codex": {(str(script),)}},
                allowed_environment={"EVIDENCE"},
                allowed_working_roots=(consumer,),
            )
            request = LaunchRequest(
                agent="codex",
                executable=sys.executable,
                args=(str(script),),
                cwd=consumer,
                env={"EVIDENCE": str(evidence)},
            )

            result = PlatformLauncher(policy).launch(resolution, request)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(evidence.read_text(encoding="utf-8"), "generic-consumer-started")
            self.assertEqual(
                result.provenance["resolution"]["project_id"],
                "disposable-generic-consumer",
            )

    def test_real_platform_declaration_reaches_harmless_agent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            script = temp / "real-agent.py"
            evidence = temp / "real-evidence.txt"
            script.write_text(
                "import os\n"
                "from pathlib import Path\n"
                "Path(os.environ['TEST_EVIDENCE_PATH']).write_text('started', encoding='utf-8')\n",
                encoding="utf-8",
            )
            resolution = RadixStartupAdapter(root / "development-platform.yaml").resolve_startup(
                session_id="real-platform-launch", agent="codex"
            )
            policy = PlatformLaunchPolicy(
                executable_by_agent={"codex": Path(sys.executable)},
                allowed_args={"codex": {(str(script),)}},
                allowed_environment={"TEST_EVIDENCE_PATH"},
                allowed_working_roots=(root,),
            )
            request = LaunchRequest(
                agent="codex",
                executable=sys.executable,
                args=(str(script),),
                cwd=root,
                env={"TEST_EVIDENCE_PATH": str(evidence)},
            )

            result = PlatformLauncher(policy).launch(resolution, request)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(evidence.read_text(encoding="utf-8"), "started")
            self.assertEqual(result.provenance["resolution"]["project_id"], "development-platform-core")

    def test_valid_request_launches_harmless_agent_with_evidence(self) -> None:
        with self.agent_fixture() as fixture:
            launcher = PlatformLauncher(fixture["policy"])
            result = launcher.launch(fixture["resolution"], fixture["request"])

            self.assertEqual(result.returncode, 0)
            self.assertTrue(fixture["evidence"].is_file())
            self.assertEqual(result.provenance["agent"], "test-agent")
            self.assertEqual(result.provenance["shell"], False)

    def test_blocked_resolution_cannot_launch(self) -> None:
        with self.agent_fixture() as fixture:
            blocked = StartupResolution(
                context=fixture["resolution"].context,
                ready=False,
                execution_allowed=False,
                blocking_reasons=("objective",),
                provenance={"blocking_reasons": ["objective"]},
            )
            with self.assertRaisesRegex(StartupLaunchError, "not executable"):
                PlatformLauncher(fixture["policy"]).launch(blocked, fixture["request"])
            self.assertFalse(fixture["evidence"].exists())

    def test_privileged_flags_and_shell_injection_are_rejected(self) -> None:
        with self.agent_fixture() as fixture:
            for args in ((str(fixture["script"]), "--privileged"), (str(fixture["script"]), "; touch /tmp/pwned")):
                request = LaunchRequest(
                    agent="test-agent",
                    executable=sys.executable,
                    args=args,
                    cwd=fixture["root"],
                )
                with self.subTest(args=args), self.assertRaises(StartupLaunchError):
                    PlatformLauncher(fixture["policy"]).launch(fixture["resolution"], request)

    def test_executable_working_directory_and_runtime_are_policy_bound(self) -> None:
        with self.agent_fixture() as fixture:
            cases = (
                LaunchRequest("test-agent", "/bin/sh", fixture["request"].args, fixture["root"]),
                LaunchRequest("test-agent", sys.executable, fixture["request"].args, Path("/tmp")),
                LaunchRequest("test-agent", sys.executable, fixture["request"].args, fixture["root"], runtime="unapproved"),
                LaunchRequest("test-agent", sys.executable, fixture["request"].args, fixture["root"], mounts=("/host:/mnt",)),
                LaunchRequest("test-agent", sys.executable, fixture["request"].args, fixture["root"], network="host"),
            )
            for request in cases:
                with self.subTest(request=request), self.assertRaises(StartupLaunchError):
                    PlatformLauncher(fixture["policy"]).launch(fixture["resolution"], request)

    def test_environment_is_allowlisted_and_not_inherited(self) -> None:
        with self.agent_fixture() as fixture:
            with patch.dict(os.environ, {"INHERITED_SECRET": "must-not-cross-boundary"}):
                request = LaunchRequest(
                    agent="test-agent",
                    executable=sys.executable,
                    args=fixture["request"].args,
                    cwd=fixture["root"],
                    env={"TEST_EVIDENCE_PATH": str(fixture["evidence"])},
                )
                PlatformLauncher(fixture["policy"]).launch(fixture["resolution"], request)
            self.assertEqual(fixture["evidence"].read_text(encoding="utf-8"), "False")

            bad = LaunchRequest(
                "test-agent",
                sys.executable,
                fixture["request"].args,
                fixture["root"],
                env={"PATH": "/tmp", "UNAPPROVED": "1"},
            )
            with self.assertRaises(StartupLaunchError):
                PlatformLauncher(fixture["policy"]).launch(fixture["resolution"], bad)

    def test_policy_cannot_launch_context_in_another_authorized_project(self) -> None:
        with self.agent_fixture() as fixture, tempfile.TemporaryDirectory() as other_directory:
            other = Path(other_directory)
            policy = PlatformLaunchPolicy(
                executable_by_agent=fixture["policy"].executable_by_agent,
                allowed_args=fixture["policy"].allowed_args,
                allowed_environment=fixture["policy"].allowed_environment,
                allowed_working_roots=(fixture["root"], other),
            )
            foreign_request = LaunchRequest(
                agent="test-agent",
                executable=sys.executable,
                args=fixture["request"].args,
                cwd=other,
                env=fixture["request"].env,
            )

            with self.assertRaisesRegex(StartupLaunchError, "does not match"):
                PlatformLauncher(policy).launch(fixture["resolution"], foreign_request)

    @staticmethod
    def agent_fixture():
        class Fixture:
            def __enter__(self):
                self.temp = tempfile.TemporaryDirectory()
                root = Path(self.temp.name)
                script = root / "agent.py"
                evidence = root / "evidence.txt"
                script.write_text(
                    "import os\n"
                    "from pathlib import Path\n"
                    "Path(os.environ['TEST_EVIDENCE_PATH']).write_text(\n"
                    "    str('INHERITED_SECRET' in os.environ), encoding='utf-8'\n"
                    ")\n",
                    encoding="utf-8",
                )
                resolution = StartupResolution(
                    context={
                        "agents": {"test-agent": True},
                        "project_id": "fixture-project",
                        "repository_root": str(root),
                    },
                    ready=True,
                    execution_allowed=True,
                    blocking_reasons=(),
                    provenance={"test": True},
                )
                policy = PlatformLaunchPolicy(
                    executable_by_agent={"test-agent": Path(sys.executable)},
                    allowed_args={"test-agent": {(str(script),)}},
                    allowed_environment={"TEST_EVIDENCE_PATH"},
                    allowed_working_roots=(root,),
                )
                request = LaunchRequest(
                    agent="test-agent",
                    executable=sys.executable,
                    args=(str(script),),
                    cwd=root,
                    env={"TEST_EVIDENCE_PATH": str(evidence)},
                )
                return {"root": root, "script": script, "evidence": evidence, "resolution": resolution, "policy": policy, "request": request}

            def __exit__(self, exc_type, exc, traceback):
                self.temp.cleanup()

        return Fixture()


if __name__ == "__main__":
    unittest.main()
