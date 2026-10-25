import pytest

from adapters.radix.pipeline import PipelineError, content_digest, create_run


def test_content_digest_is_deterministic_for_mapping_order():
    assert content_digest({"b": 2, "a": 1}) == content_digest({"a": 1, "b": 2})


def test_run_requires_source_revision():
    from tests.test_radix_pipeline import pipeline_definition

    with pytest.raises(PipelineError, match="source revision"):
        create_run(pipeline_definition(), source_revision=" ")
