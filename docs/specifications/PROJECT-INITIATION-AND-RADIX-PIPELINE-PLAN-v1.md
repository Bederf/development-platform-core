---
title: Project Initiation and Radix Pipeline Plan v1
type: architecture-plan
status: proposed
authority: proposal
---

# Project Initiation and Radix Pipeline Plan v1

## Decision

Keep `./radix.sh` as the stable entry point. Project initiation and multi-agent coordination are Core capabilities behind that entry point; they are not replacement launchers and do not create an independent orchestration system.

The canonical project definition is the machine-readable `project-definition.v1` document. Human-readable Markdown is derived documentation. Existing `project-governance.v1` remains the authority for ownership, delegated authority, review and approval policy and is referenced by digest rather than copied.

## Radix compatibility boundary

Existing behavior remains unchanged:

```text
./radix.sh --codex
./radix.sh --claude
./radix.sh --opencode
./radix.sh init
```

Future pipeline behavior is additive and must be explicitly selected, for example:

```text
./radix.sh pipeline --plan <approved-plan>
```

No existing agent mode may implicitly become multi-agent, create worktrees, merge branches, or activate providers.

## Governed pipeline shape

The proposed pipeline has four bounded roles:

1. Architect: reads the approved objective and produces a plan artifact.
2. Worker: consumes only the approved plan and produces implementation changes in an isolated workspace.
3. Validator: evaluates the worker result and emits validation evidence.
4. Supervisor: reviews the evidence and explicitly authorizes any merge or promotion.

The Core contract owns identity, authorization, lifecycle, correlation, artifact binding, failure states and evidence interpretation. Orca owns terminal/worktree mechanics and remote session transport. Radix remains the routing and startup authority.

## Required controls

- Every run has a unique run id and binds to one project definition, phase/task authority and source revision.
- Artifacts are run-scoped and content-addressed; later roles cannot silently replace earlier approved inputs.
- A failed or disconnected provider leaves the run incomplete or blocked; it cannot imply success.
- Provider adapters must declare timeout, heartbeat and disconnect behavior;
  unqualified retries are disabled and a missed heartbeat produces a blocked
  or failed outcome.
- Worktree creation, branch mutation, merge and provider activation require explicit capability and authority checks.
- Supervisor approval is a hard gate before merge or promotion.
- The initial implementation uses fake Orca/provider fixtures before any live remote execution is qualified.

## Delivery sequence

1. Qualify `project-definition.v1` against existing governance, bootstrap and phase-admission semantics.
2. Add canonical digest and approval/admission adapters without changing consumer repositories.
3. Define a candidate pipeline contract for run identity, role hand-offs, artifacts, workspace references and approval gates.
4. Add fake-provider conformance tests for the pipeline contract.
5. Add a Radix pipeline mode that is review-only by default and preserves all current modes.
6. Qualify Orca transport/worktree execution separately; do not make Orca a Core dependency until the governed requirement is accepted.
7. Adopt from consumer repositories only after an immutable Core checkpoint is explicitly qualified.

## Stop conditions

This plan does not authorize live agent execution, automatic merge, provider activation, consumer-repository changes or a new workspace/transport contract promotion. Any such change requires its own admitted phase and authority record.
