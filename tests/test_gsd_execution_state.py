import pytest

from adapters.gsd_execution_state import (
    ATTEMPT_TRANSITIONS,
    TASK_TRANSITIONS,
    AttemptState,
    ExecutionStateError,
    RetryProjection,
    TaskState,
    TerminalObservation,
    authorize_retry,
    classify_observation,
    project_retry,
    resolve_terminal_observations,
    transition_attempt,
    transition_task,
)


def observation(sequence, outcome, digest):
    return TerminalObservation(sequence, outcome, "op-1", digest)


def test_task_transition_table_allows_declared_paths_and_rejects_terminal_reopen():
    for current, targets in TASK_TRANSITIONS.items():
        for target in targets:
            if target is TaskState.SUCCEEDED:
                assert transition_task(
                    current,
                    target,
                    accepted_terminal_observation=observation(
                        1,
                        AttemptState.SUCCEEDED,
                        "accepted-success",
                    ),
                ) is target
            else:
                assert transition_task(current, target) is target
    with pytest.raises(ExecutionStateError):
        transition_task(TaskState.SUCCEEDED, TaskState.RUNNING)
    with pytest.raises(ExecutionStateError):
        transition_task(TaskState.PENDING, TaskState.RUNNING)


def test_every_undeclared_task_transition_fails_closed():
    for current in TaskState:
        for requested in TaskState:
            if requested not in TASK_TRANSITIONS[current]:
                with pytest.raises(ExecutionStateError):
                    transition_task(current, requested)


def test_attempt_transition_table_allows_declared_paths_and_rejects_terminal_reopen():
    for current, targets in ATTEMPT_TRANSITIONS.items():
        for target in targets:
            assert transition_attempt(current, target) is target
    with pytest.raises(ExecutionStateError):
        transition_attempt(AttemptState.SUCCEEDED, AttemptState.RUNNING)
    with pytest.raises(ExecutionStateError):
        transition_attempt(AttemptState.CANCEL_REQUESTED, AttemptState.SUCCEEDED)


def test_dispatched_only_allows_running_or_unknown_per_adr():
    assert transition_attempt(AttemptState.DISPATCHED, AttemptState.RUNNING) is AttemptState.RUNNING
    assert transition_attempt(AttemptState.DISPATCHED, AttemptState.UNKNOWN) is AttemptState.UNKNOWN
    for target in (
        AttemptState.SUCCEEDED,
        AttemptState.FAILED,
        AttemptState.TIMED_OUT,
        AttemptState.CANCEL_REQUESTED,
    ):
        with pytest.raises(ExecutionStateError):
            transition_attempt(AttemptState.DISPATCHED, target)


def test_every_undeclared_attempt_transition_fails_closed():
    for current in AttemptState:
        for requested in AttemptState:
            if requested not in ATTEMPT_TRANSITIONS[current]:
                with pytest.raises(ExecutionStateError):
                    transition_attempt(current, requested)


def test_task_and_attempt_state_domains_are_distinct():
    for shared_name in ("RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "UNKNOWN"):
        task_state = TaskState[shared_name]
        attempt_state = AttemptState[shared_name]
        with pytest.raises(ExecutionStateError):
            transition_task(task_state, attempt_state)
        with pytest.raises(ExecutionStateError):
            transition_attempt(attempt_state, task_state)


def test_task_success_requires_controller_accepted_successful_attempt():
    with pytest.raises(ExecutionStateError, match="accepted terminal observation"):
        transition_task(TaskState.RUNNING, TaskState.SUCCEEDED)
    with pytest.raises(ExecutionStateError, match="successful attempt"):
        transition_task(
            TaskState.RUNNING,
            TaskState.SUCCEEDED,
            accepted_terminal_observation=observation(1, AttemptState.FAILED, "failed"),
        )
    assert transition_task(
        TaskState.RUNNING,
        TaskState.SUCCEEDED,
        accepted_terminal_observation=observation(1, AttemptState.SUCCEEDED, "success"),
    ) is TaskState.SUCCEEDED


def test_unknown_state_values_fail_closed():
    with pytest.raises(ExecutionStateError, match="unknown task state"):
        transition_task("NOT_A_TASK_STATE", TaskState.READY)
    with pytest.raises(ExecutionStateError, match="unknown attempt state"):
        transition_attempt("NOT_AN_ATTEMPT_STATE", AttemptState.RUNNING)


def test_terminal_race_uses_sequence_not_input_or_wall_clock_order():
    result = resolve_terminal_observations([
        observation(4, AttemptState.SUCCEEDED, "success"),
        observation(2, AttemptState.TIMED_OUT, "timeout"),
    ])
    assert result.winner.outcome is AttemptState.TIMED_OUT
    assert [item.outcome for item in result.late] == [AttemptState.SUCCEEDED]


@pytest.mark.parametrize(
    ("winner", "late"),
    [
        (winner, late)
        for winner in (
            AttemptState.SUCCEEDED,
            AttemptState.FAILED,
            AttemptState.TIMED_OUT,
            AttemptState.CANCELLED,
        )
        for late in (
            AttemptState.SUCCEEDED,
            AttemptState.FAILED,
            AttemptState.TIMED_OUT,
            AttemptState.CANCELLED,
        )
        if winner is not late
    ],
)
def test_every_terminal_race_pair_uses_commit_sequence_and_preserves_late_evidence(winner, late):
    result = resolve_terminal_observations([
        observation(2, late, f"late-{late.value}"),
        observation(1, winner, f"winner-{winner.value}"),
    ])
    assert result.winner.outcome is winner
    assert [item.outcome for item in result.late] == [late]


def test_terminal_race_duplicate_is_retained_alongside_late_evidence():
    result = resolve_terminal_observations([
        observation(3, AttemptState.FAILED, "late"),
        observation(2, AttemptState.SUCCEEDED, "winner"),
        observation(4, AttemptState.SUCCEEDED, "winner"),
    ])
    assert result.winner.outcome is AttemptState.SUCCEEDED
    assert [item.outcome for item in result.duplicates] == [AttemptState.SUCCEEDED]
    assert [item.outcome for item in result.late] == [AttemptState.FAILED]


def test_equal_terminal_sequence_fails_closed():
    with pytest.raises(ExecutionStateError, match="ambiguous"):
        resolve_terminal_observations([
            observation(2, AttemptState.SUCCEEDED, "success"),
            observation(2, AttemptState.FAILED, "failure"),
        ])


def test_equal_sequence_exact_replay_is_an_idempotent_duplicate():
    result = resolve_terminal_observations([
        observation(2, AttemptState.SUCCEEDED, "success"),
        observation(2, AttemptState.SUCCEEDED, "success"),
    ])
    assert result.winner.outcome is AttemptState.SUCCEEDED
    assert len(result.duplicates) == 1


def test_same_digest_with_different_outcome_fails_closed():
    with pytest.raises(ExecutionStateError, match="conflicting terminal payloads"):
        resolve_terminal_observations([
            observation(1, AttemptState.SUCCEEDED, "same"),
            observation(2, AttemptState.FAILED, "same"),
        ])


def test_duplicate_and_late_observations_do_not_replace_commitment():
    committed = observation(2, AttemptState.SUCCEEDED, "same")
    assert classify_observation(committed, observation(3, AttemptState.SUCCEEDED, "same")) == "duplicate"
    assert classify_observation(committed, observation(4, AttemptState.FAILED, "different")) == "late"


def test_same_digest_with_different_outcome_is_not_a_duplicate():
    with pytest.raises(ExecutionStateError, match="conflicting observation payload"):
        classify_observation(
            observation(2, AttemptState.SUCCEEDED, "same"),
            observation(3, AttemptState.FAILED, "same"),
        )


def test_same_digest_before_commitment_fails_closed_as_ordering_fault():
    with pytest.raises(ExecutionStateError, match="conflicting observation sequence"):
        classify_observation(
            observation(3, AttemptState.SUCCEEDED, "same"),
            observation(2, AttemptState.SUCCEEDED, "same"),
        )


@pytest.mark.parametrize(
    ("sequence", "outcome", "operation_id", "digest", "message"),
    [
        (0, AttemptState.SUCCEEDED, "op-1", "digest", "positive"),
        (1, "SUCCEEDED", "op-1", "digest", "outcome"),
        (1, AttemptState.RUNNING, "op-1", "digest", "non-terminal"),
        (1, AttemptState.SUCCEEDED, "", "digest", "identity"),
        (1, AttemptState.SUCCEEDED, "op-1", "", "identity"),
    ],
)
def test_terminal_observation_validation_fails_closed(sequence, outcome, operation_id, digest, message):
    with pytest.raises(ExecutionStateError, match=message):
        TerminalObservation(sequence, outcome, operation_id, digest)


def test_empty_terminal_observation_set_fails_closed():
    with pytest.raises(ExecutionStateError, match="required"):
        resolve_terminal_observations([])


def test_conflicting_operation_identities_fail_closed():
    with pytest.raises(ExecutionStateError, match="operation identities"):
        resolve_terminal_observations([
            observation(1, AttemptState.SUCCEEDED, "a"),
            TerminalObservation(2, AttemptState.FAILED, "op-2", "b"),
        ])


def test_observation_operation_mismatch_fails_closed():
    with pytest.raises(ExecutionStateError, match="operation identity mismatch"):
        classify_observation(
            observation(1, AttemptState.SUCCEEDED, "a"),
            TerminalObservation(2, AttemptState.FAILED, "op-2", "b"),
        )


def test_conflicting_prior_sequence_fails_closed():
    with pytest.raises(ExecutionStateError, match="conflicting"):
        classify_observation(observation(3, AttemptState.SUCCEEDED, "a"), observation(2, AttemptState.FAILED, "b"))


def test_unknown_is_non_success_and_not_automatically_retryable():
    with pytest.raises(ExecutionStateError):
        authorize_retry(AttemptState.UNKNOWN, new_attempt_id="a2", prior_attempt_id="a1", task_retry_safe=True)
    with pytest.raises(ExecutionStateError):
        authorize_retry(AttemptState.SUCCEEDED, new_attempt_id="a2", prior_attempt_id="a1", task_retry_safe=True)


def test_retry_requires_new_identity_and_explicit_safety():
    assert authorize_retry(AttemptState.FAILED, new_attempt_id="a2", prior_attempt_id="a1", task_retry_safe=True)
    assert authorize_retry(AttemptState.UNKNOWN, new_attempt_id="a2", prior_attempt_id="a1", task_retry_safe=True, qualified_unknown_replay=True)
    with pytest.raises(ExecutionStateError):
        authorize_retry(AttemptState.FAILED, new_attempt_id="a1", prior_attempt_id="a1", task_retry_safe=True)
    with pytest.raises(ExecutionStateError):
        authorize_retry(AttemptState.FAILED, new_attempt_id="a2", prior_attempt_id="a1", task_retry_safe=False)


def test_retry_projection_preserves_lineage_and_starts_new_attempt_at_created():
    projection = project_retry(
        AttemptState.FAILED,
        new_attempt_id="a2",
        prior_attempt_id="a1",
        task_retry_safe=True,
    )
    assert isinstance(projection, RetryProjection)
    assert projection.prior_attempt_id == "a1"
    assert projection.new_attempt_id == "a2"
    assert projection.prior_state is AttemptState.FAILED
    assert projection.projected_state is AttemptState.CREATED


def test_unknown_retry_projection_requires_qualified_replay():
    with pytest.raises(ExecutionStateError):
        project_retry(
            AttemptState.UNKNOWN,
            new_attempt_id="a2",
            prior_attempt_id="a1",
            task_retry_safe=True,
        )
    projection = project_retry(
        AttemptState.UNKNOWN,
        new_attempt_id="a2",
        prior_attempt_id="a1",
        task_retry_safe=True,
        qualified_unknown_replay=True,
    )
    assert projection.prior_state is AttemptState.UNKNOWN
    assert projection.projected_state is AttemptState.CREATED


def test_concurrent_retry_owner_blocks_retry():
    with pytest.raises(ExecutionStateError, match="concurrent owner"):
        authorize_retry(
            AttemptState.FAILED,
            new_attempt_id="a2",
            prior_attempt_id="a1",
            task_retry_safe=True,
            concurrent_owner=True,
        )
