# Review Policies

## Independence

The reviewer receives a fresh context. The implementation agent's private
reasoning, unfinished plan, and conversation history are not review evidence.
A same-session self-review is labelled `self_review` and cannot satisfy the
independent-review gate.

## Findings

Each finding must include:

- stable id;
- severity: `blocker`, `major`, `minor`, or `advisory`;
- confidence;
- title and description;
- category;
- evidence reference;
- actionable recommendation;
- source reviewer.

## Completion gate

The reviewer may recommend a disposition, but GSD controls lifecycle state.
`CHANGES_REQUIRED` and `BLOCKED` cannot be converted into `completed` without
a later review attempt that satisfies the gate.

The GSD fix/review loop is bounded to three correction cycles. After the third
unresolved cycle, the run is escalated with all prior evidence preserved.
