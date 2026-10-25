from __future__ import annotations

import pytest

from adapters.spec_kit_mapping import SpecKitMappingError, map_operation, validate_provider_claim


@pytest.mark.parametrize(
    ("operation", "stage", "kind"),
    [
        ("/specify", "SPECIFICATION", "specification"),
        ("/speckit.specify", "SPECIFICATION", "specification"),
        ("/plan", "PLAN", "plan"),
        ("/speckit.plan", "PLAN", "plan"),
        ("/tasks", "TASKS", "task_list"),
        ("/speckit.tasks", "TASKS", "task_list"),
        ("/implement", "IMPLEMENTATION", "implementation"),
        ("/speckit.implement", "IMPLEMENTATION", "implementation"),
        ("/converge", "CONVERGENCE", "convergence"),
        ("/speckit.converge", "CONVERGENCE", "convergence"),
    ],
)
def test_spec_kit_operations_map_to_core_stages(operation: str, stage: str, kind: str) -> None:
    mapping = map_operation(operation)
    assert mapping["stage"] == stage
    assert mapping["artifact_kind"] == kind


def test_convergence_cannot_be_verification_or_acceptance() -> None:
    mapping = map_operation("/converge")
    assert mapping["authority"] == "assessment_only"
    with pytest.raises(SpecKitMappingError):
        validate_provider_claim("/converge", "VERIFICATION", "verification")
    with pytest.raises(SpecKitMappingError):
        validate_provider_claim("/converge", "ACCEPTANCE", "acceptance")


def test_implementation_is_report_only() -> None:
    mapping = map_operation("/implement")
    assert mapping["authority"] == "report_only"


def test_unknown_operation_fails_closed() -> None:
    with pytest.raises(SpecKitMappingError):
        map_operation("/auto-accept")


def test_mapping_result_cannot_mutate_registry() -> None:
    mapping = map_operation("/plan")
    mapping["stage"] = "ACCEPTANCE"
    assert map_operation("/plan")["stage"] == "PLAN"
