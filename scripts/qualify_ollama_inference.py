"""Bounded native Ollama observations, not a governed execution adapter.

Only loopback, fixed synthetic prompts and an already installed pinned model.
No pull, installation, daemon changes, retries, redirects or user input prompts.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from datetime import datetime, timezone
from pathlib import Path
import time


HOST, PORT = "127.0.0.1", 11434
MODEL = "llama3.2:1b"
VERSION = "0.20.0"
MODEL_DIGEST = "baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878"
BODY_LIMIT = 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def request(path, payload=None):
    connection = http.client.HTTPConnection(HOST, PORT, timeout=30)
    started = time.monotonic()
    try:
        encoded = None if payload is None else json.dumps(payload).encode()
        connection.request("GET" if payload is None else "POST", path, body=encoded,
                           headers={"Content-Type": "application/json"} if encoded else {})
        response = connection.getresponse()
        raw = response.read(BODY_LIMIT + 1)
        if len(raw) > BODY_LIMIT:
            raise ValueError("response body exceeds qualification bound")
        return {"path": path, "status": response.status, "body": json.loads(raw),
                "elapsed_seconds": round(time.monotonic()-started, 4),
                "request_digest": digest(payload) if payload is not None else None}
    except (OSError, ValueError, http.client.HTTPException) as error:
        # A client timeout is not proof that remote computation terminated.
        return {"path": path, "error_type": type(error).__name__, "remote_outcome": "unknown",
                "elapsed_seconds": round(time.monotonic()-started, 4)}
    finally:
        connection.close()


def model_entry(record):
    matches = [m for m in record.get("body", {}).get("models", []) if m.get("name") == MODEL]
    return matches[0] if len(matches) == 1 else None


def ready(version, tags, running):
    entry = model_entry(tags)
    return (version.get("status") == tags.get("status") == running.get("status") == 200
            and version["body"].get("version") == VERSION
            and entry is not None and entry.get("digest") == MODEL_DIGEST
            and not entry.get("remote_host") and not entry.get("remote_model")
            and running["body"].get("models") == [])


def run(execute=False):
    report = {"version": "1.0.0", "observed_at": datetime.now(timezone.utc).isoformat(),
              "status": "native-observation-only", "endpoint": f"http://{HOST}:{PORT}",
              "expected_runtime_version": VERSION, "model": MODEL, "expected_model_digest": MODEL_DIGEST,
              "client_retries": 0, "redirects_followed": 0, "synthetic_only": True,
              "provider_conformance": "not_established", "requests": []}
    binary = Path("/usr/local/bin/ollama")
    report["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest() if binary.is_file() else None
    version, tags, running = [request(path) for path in ("/api/version", "/api/tags", "/api/ps")]
    report["version_before"], report["tags_before"], report["running_before"] = version, tags, running
    if not execute or not ready(version, tags, running):
        report["generation_status"] = "not_requested" if not execute else "blocked_precondition"
        return report
    show = request("/api/show", {"model": MODEL})
    if show.get("status") != 200:
        report["generation_status"] = "blocked_model_metadata"
        report["show_status"] = show.get("status", "unknown")
        return report
    body = show["body"]
    report["model_metadata"] = {"body_digest": digest(body), "details": body.get("details"),
        "capabilities": body.get("capabilities"), "parameters_digest": digest(body.get("parameters")),
        "template_digest": digest(body.get("template")), "model_info_digest": digest(body.get("model_info"))}
    cases = [("short-response", MODEL, "Question: What is 2 + 2?\nAnswer:", 16),
             ("token-ceiling", MODEL, "Continue the sequence: one, two, three,", 1),
             ("malformed-prompt", MODEL, ["invalid type"], 1),
             ("missing-model", "core-qualification-missing-model:synthetic", "Synthetic diagnostic.", 1)]
    for name, model, prompt, limit in cases:
        payload = {"model": model, "prompt": prompt, "raw": True, "stream": False,
                   "options": {"num_predict": limit}, "keep_alive": "10s"}
        # Each case is an independent diagnostic, never a retry of a failed case.
        record = request("/api/generate", payload)
        record.update(case=name, request=payload)
        report["requests"].append(record)
        if "error_type" in record:
            report["generation_status"] = "stopped_unknown_remote_outcome"
            break
        report.setdefault("running_observations", []).append(request("/api/ps"))
    else:
        report["generation_status"] = "diagnostics_completed"
    report["tags_after"] = request("/api/tags")
    report["version_after"] = request("/api/version")
    report["selected_model_digest_unchanged"] = (model_entry(report["tags_after"]) or {}).get("digest") == MODEL_DIGEST
    report["limitations"] = [
        "Native API probes do not pass through the candidate governed execution composition.",
        "No independent per-request model digest or destination attestation is provided by generate.",
        "Inventory correlation cannot exclude concurrent model replacement (including replace-and-restore).",
        "Server cloud-disable configuration, retention, egress and hidden retry behavior were not verified.",
        "Timeout/cancellation and full live-provider matrix were not exercised.",
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-synthetic", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; preserve prior evidence and choose a new path")
    report = run(args.run_synthetic)
    report["probe_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"output": str(args.output), "generation_status": report["generation_status"],
                      "cases": [{"case": c["case"], "status": c.get("status"),
                                 "done_reason": c.get("body", {}).get("done_reason"),
                                 "eval_count": c.get("body", {}).get("eval_count")} for c in report["requests"]]}))


if __name__ == "__main__":
    main()
