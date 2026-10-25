---
title: Radix Agent Pipeline Contract v1
type: candidate-contract
status: candidate-only
schema: radix-agent-pipeline.v1
---

# Radix Agent Pipeline Contract v1

This is a candidate contract for a bounded Radix-native multi-agent hand-off. It is not promoted and does not authorize live execution.

## Ownership boundary

Core owns pipeline identity, project-definition binding, stage dependencies, authorization requirements, artifact lineage, lifecycle outcomes and evidence interpretation. Radix owns startup authority and explicit command routing. An execution provider such as Orca may own terminals, worktrees, remote sessions and process mechanics, but cannot grant authority or establish verification.

The provider is deliberately represented only by an optional neutral reference. The candidate contract contains no Orca-specific fields and does not make Orca a Core dependency.

## Required hand-offs

- `architect` receives an admitted objective and emits an implementation plan.
- `worker` receives the content-addressed approved plan and emits implementation artifacts.
- `validator` receives the worker result and emits validation evidence.
- `supervisor` receives the plan, implementation identity and validation evidence and makes the explicit merge/promotion decision.

Each stage declares its dependencies and authorization requirement. When
authorization is required, the stage carries an authorization reference bound
to its stage identity, authority, decision and evidence digest. A missing,
stale or contradictory input blocks the stage; it cannot be inferred from a
provider transcript.

## Safety rules

- A pipeline binds to one canonical project definition and source revision.
- Evidence is run-scoped and content-addressed.
- Provider failure is terminal or blocked, never success by omission.
- The provider boundary declares a timeout, heartbeat interval, missed-heartbeat
  limit and disconnect outcome. Retries are disabled until separately qualified.
- Merge and promotion remain disabled unless the approval gate is satisfied.
- Worktree and remote transport behavior require a separately qualified provider adapter.

## Promotion requirements

Promotion requires reconciliation against existing GSD execution, session, evidence and approval contracts; fake-provider conformance; isolation and recovery tests; independent architecture review; and an explicit authority decision. Until then this schema remains candidate-only.
