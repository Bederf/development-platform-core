---
name: gsd-precheck-gate
version: 1.1.0
description: Project-local precheck and phase-closeout gate for GSD phase execution.
---

# GSD Precheck Gate

Use this gate before architecture challenge or implementation for a phase.

## Procedure

1. Read the phase specification and its declared dependencies.
2. Inspect the repository paths and contracts named by the phase.
3. Search the plans, specifications, tests, and existing implementation for
   each suspected concern.
4. Return only concerns that are novel and not already addressed by the phase
   artifacts.
5. Classify each result as `NOVEL`, `ALREADY_ADDRESSED`, or `NOT_APPLICABLE`.

## Output

Return a bounded report containing:

```text
NOVEL_COUNT: <number>
ALREADY_ADDRESSED_COUNT: <number>
NOT_APPLICABLE_COUNT: <number>

NOVEL_ISSUES:
- id: PRECHECK-001
  classification: architecture | requirement | implementation | dependency
  evidence: <path and heading or line>
  impact: <plain-language consequence>
  recommendation: <bounded next action>
```

Do not authorize implementation, approve policy, dismiss a requirement, or
replace independent verification. A concern that requires an owner decision
must be returned with its evidence and remain unresolved until governed
authority confirms it.

## Phase closeout and next-step decision

After implementation, verification and the required acceptance decision have
completed, record a phase closeout before proposing further work. The closeout
must distinguish these states:

- `CLOSED` — all required acceptance conditions passed and no limitation
  remains;
- `CLOSED_WITH_LIMITATIONS` — the owner accepted named residual conditions
  that do not authorize later work; or
- `BLOCKED` — a required review, acceptance, authority record or prerequisite
  is missing or failed.

The closeout record must reference the phase artifact, specification identity,
implementation evidence, verification result, acceptance decision and any
accepted limitations. Do not infer acceptance from a passing test or review,
and do not replace an attributable acceptance decision with a status edit.

When a phase is closed, present the owner with only evidence-based next-step
options applicable to the recorded state. Typical options are:

1. reconcile an accepted limitation within its existing bounded authority;
2. prepare a separately governed next-phase artifact for owner consideration;
3. defer further work while preserving the current closeout; or
4. stop because a prerequisite or authority decision is unresolved.

These options are decisions for the owner, not automatic workflow transitions.
GSD must not create, bind, authorize or begin a later phase merely because the
previous phase passed or was accepted. A later phase requires its own
specification and sidecar, subject-bound authority resolution,
implementation authorization, verification gates and acceptance. If an
accepted limitation is a prerequisite for later work, state that dependency
explicitly and keep the later work unauthorized until it is resolved or the
owner records an applicable decision.

The closeout response should use this bounded format:

```text
PHASE_STATUS: CLOSED | CLOSED_WITH_LIMITATIONS | BLOCKED
EVIDENCE: <paths and digests where available>
LIMITATIONS: <accepted residual conditions or none>
NEXT_OPTIONS:
- <evidence-based option>
- <evidence-based option>
OWNER_DECISION_REQUIRED: yes | no
AUTHORIZATION_GRANTED: no, unless a separate attributable authorization is recorded
```

An owner decision to prepare a later phase is not implementation
authorization. An owner decision to authorize implementation must remain a
separate attributable record and must be checked against the later phase's
scope and exclusions.
