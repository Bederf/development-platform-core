import json
from pathlib import Path

import pytest

from adapters.review_evidence import ReviewEvidenceError, ReviewEvidenceStore


def test_review_evidence_is_redacted_content_addressed_and_bounded(tmp_path: Path) -> None:
    observation = {
        "provider": "omniroute",
        "model": "oc/test",
        "gsd_request_id": "gsd-001",
        "provider_request_id": "provider-request-001",
        "omniroute_call_id": "call-001",
        "generation_id": "generation-001",
        "raw_provider_status": 200,
        "cache_status": "miss",
        "fresh_request": True,
        "response_format": {"type": "json_schema"},
        "schema_version": "code-review-result.v1",
        "raw_provider_response": '{"authorization":"Bearer secret","result":"PASS"}',
    }
    result = ReviewEvidenceStore(tmp_path, retention_days=7).persist(observation)
    stored = Path(result["raw_response_ref"])
    manifest = json.loads((tmp_path / "provider-request-001" / "manifest.json").read_text())
    assert stored.read_text() == '{"authorization":"Bearer [REDACTED]","result":"PASS"}'
    assert manifest["raw_response_sha256"] == result["raw_response_digest"]
    assert manifest["retention_until"]
    assert oct(stored.stat().st_mode & 0o777) == "0o600"


def test_review_evidence_refuses_overwrite_and_invalid_request_id(tmp_path: Path) -> None:
    store = ReviewEvidenceStore(tmp_path)
    observation = {"provider_request_id": "request-1", "raw_provider_response": "{}"}
    store.persist(observation)
    with pytest.raises(ReviewEvidenceError, match="already exists"):
        store.persist(observation)
    with pytest.raises(ReviewEvidenceError, match="path-safe"):
        store.persist({"provider_request_id": "../escape", "raw_provider_response": "{}"})
