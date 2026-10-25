# Code Review Execution Context

The runtime derives this context from the versioned AOC and a task frame. It
must contain only the effective review mission, permissions, evidence, tools,
policies, and success criteria for the current attempt.

## Review sequence

1. Load and validate the AOC and frame.
2. Confirm the context is fresh and separate from the implementation attempt.
3. Read the governing specification and acceptance criteria.
4. Inspect the complete diff and changed-file relationships.
5. Inspect focused tests and operator-supplied verification evidence.
6. Check applicable contracts, ADRs, security constraints, and scope boundaries.
7. Return structured findings and a disposition.

`PASS` means no material findings remain. `PASS_WITH_ADVISORIES` means only
non-blocking findings remain. `CHANGES_REQUIRED` means the implementation must
return to the coding agent. The reviewer does not apply the fixes.
