#!/usr/bin/env python3
"""Run the bounded Spec Kit artifact-bridge qualification harness.

This command imports existing workspace artifacts only. It does not invoke an
agent, run Spec Kit commands, approve Core gates, or establish acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from adapters.spec_kit_live import SpecKitLiveAdapter, SpecKitLiveAdapterError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--version", default="1.0.4", dest="provider_version")
    args = parser.parse_args()

    adapter = SpecKitLiveAdapter(workspace=args.workspace, provider_version=args.provider_version)
    operations = (
        ("/speckit.specify", "specs/001-core-bridge/spec.md", "spec-001", ("intent-001",)),
        ("/speckit.plan", "specs/001-core-bridge/plan.md", "plan-001", ("spec-001",)),
        ("/speckit.tasks", "specs/001-core-bridge/tasks.md", "tasks-001", ("plan-001",)),
        ("/speckit.implement", "implementation.md", "implementation-001", ("tasks-001",)),
        ("/speckit.converge", "convergence.md", "convergence-001", ("implementation-001",)),
    )
    results: list[dict[str, object]] = []
    try:
        for operation, path, artifact_ref, input_refs in operations:
            if not (args.workspace / path).is_file():
                continue
            result = adapter.import_artifact(
                operation,
                artifact_ref=artifact_ref,
                artifact_path=path,
                input_refs=input_refs,
                requirements_complete=operation == "/speckit.converge",
            )
            artifact = result.get("proposal", result.get("artifact_proposal", {}))
            results.append({
                "operation": operation,
                "artifact_ref": artifact_ref,
                "result_type": result.get("report_type", "proposal"),
                "stage": artifact.get("artifact", {}).get("stage") if isinstance(artifact, dict) else None,
                "digest": result["provider_provenance"]["content_digest"],
            })
    except (SpecKitLiveAdapterError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "CONFORMANCE_CANDIDATE", "provider_version": args.provider_version, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
