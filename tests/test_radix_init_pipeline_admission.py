import io
import json

from adapters.radix.cli import main
from tests.test_project_definition_adapter import _bound_definition


def test_pipeline_cli_emits_review_only_run(tmp_path):
    from tests.test_radix_pipeline import pipeline_definition

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(pipeline_definition()), encoding="utf-8")
    output = io.StringIO()
    assert main(["pipeline", "--plan", str(plan), "--source-revision", "abc123", "--run-id", "cli-1", "--json"], stdout=output) == 0
    result = json.loads(output.getvalue())
    assert result["status"] == "review_only_ready"
    assert result["run"]["run_id"] == "cli-1"


def test_init_validates_project_definition_without_writing(tmp_path):
    from adapters.radix.init_cli import main as init_main

    document, _ = _bound_definition(tmp_path)
    definition = tmp_path / "project-definition.json"
    definition.write_text(json.dumps(document), encoding="utf-8")
    output = io.StringIO()
    assert init_main(["--project", str(tmp_path), "--project-definition", str(definition), "--validate-project-definition", "--json"], stdout=output) == 0
    result = json.loads(output.getvalue())
    assert result["status"] == "validated"
    assert result["project_id"] == "example-project"
