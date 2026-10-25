---
title: "Governed Engineering Loop v1"
type: "capability-specification"
status: "experimental"
version: "1.0.0"
tags:
  - development-platform
  - agent-workflow
  - governance
---

# Governed Engineering Loop v1

The Governed Engineering Loop is a provider-neutral Development Platform Core
capability. It compiles the minimum useful project state for an agent and
coordinates bounded engineering work without making the compiled context an
authority source.

Its machine-readable capability definition is
[`governed-engineering-loop.v1.0.0.json`](../../capabilities/governed-engineering-loop.v1.0.0.json).
It composes the existing `agent-startup-context.v1`, `policy-decision.v1`,
`engineering-execution.v1`, `gsd-planning-lifecycle.v1`, and
`verification-result.v1` contracts.

## Boundary

```text
Authority sources ──► policy decision ──► authorized execution
        │                                      │
        └──► project snapshot ──► agent ──► verification
```

The project snapshot is a governed derived context artifact. It describes
project facts, current state, relevant context, uncertainty, and a proposed
next action. It never grants permission. Action-oriented fields such as
`next_action` and `recommended_action` MUST NOT be interpreted as
authorization.

Authorization MUST be independently resolvable from its declared authority
source, scope, validity, and status. Missing, ambiguous, expired, revoked, or
invalid authorization MUST block the affected state-changing operation even if
the snapshot recommends it.

## Execution loop

```text
context loaded
  → intent captured
  → plan proposed
  → plan authorization resolved
  → implementation
  → tests
  → review
  → commit/close-out
  → independent verification
```

Once a bounded plan has an applicable authorization, implementation, tests,
review, and commit within that scope proceed as one continuous execution loop.
The agent MUST NOT request repeated approval for ordinary in-scope steps.

The agent MUST re-check or escalate only when work requires:

- scope expansion or a materially different plan;
- destructive or irreversible operations;
- production changes or external side effects;
- secrets, credentials, or protected data;
- expired, revoked, ambiguous, or otherwise invalid authorization.

Test failures within scope should be diagnosed and corrected in scope. The
agent may stop when a correction would materially change the plan or cross a
protected boundary.

## Owner-decision gates

When a required owner decision is missing, the agent MUST first search the
declared authoritative sources. It MUST classify each result as `confirmed`,
`incomplete`, `conflicting`, or `absent` and preserve source provenance.

If a decision remains unresolved, the agent MUST issue a guided,
plain-language decision request containing:

- the decision and why it matters;
- evidence found, including source path/section and source identity;
- a clearly labelled recommendation when useful;
- approve, modify, and defer choices;
- the consequence of each choice;
- a plain-language reply example.

The agent MUST NOT invent, infer, or silently approve policy. After an owner
answers, the response is translated into the governed decision representation,
with provenance and uncertainty preserved. All work covered by the approved
scope then resumes without intermediate approval pauses.

## Evidence and uncertainty

Material snapshot claims and owner decisions SHOULD carry:

```yaml
value: <claim or decision>
status: confirmed | incomplete | conflicting | absent
source: <authority source path or provider reference>
source_hash: <immutable source identity when available>
observed_at: <timestamp>
```

`confirmed` means confirmed by the cited source or derivation process; it does
not mean universally true. Evidence, evaluation, authorization, and
verification remain separate semantic operations.

## Adapter rule

Codex, Claude, DSH, and future harnesses may expose this capability through
their own skill formats, invocation names, prompt mechanisms, MCP clients, and
transport lifecycle. An adapter MUST preserve the Core semantics above and
MUST NOT turn a snapshot, skill activation, capability advertisement, or
provider lifecycle result into authorization.

GSD terminology such as `gsd:master` belongs to a harness/workflow adapter. It
is not Core vocabulary.
