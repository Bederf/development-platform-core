# Development Platform Contracts v1 — Freeze

**Status:** frozen
**Frozen:** 2026-07-30
**Baseline commits:** `3488b50`, `8dcdce4`, `b16bb57`

## Frozen contracts

- `development-platform.v1`
- `agent-startup-context.v1`
- `repository-intelligence.v1`
- `agent-adapter.v1`
- `forge-adapter.v1`
- `verification-result.v1`
- `gsd-planning-lifecycle.v1`
- `development-workflow.v1`

## Freeze rule

Phase 004 and later consumer work MUST treat these contracts as immutable.

If a consumer exposes a problem, classify it first as:

1. consumer configuration issue;
2. adapter issue;
3. genuine contract defect; or
4. optional capability requirement.

No contract modification is permitted without a new evidence-led phase and a
versioning decision. Breaking changes require a new major contract version.

## Amendment 2026-09-08

`development-workflow.v1` was promoted after owner approval, independent
review (`PASS_WITH_ADVISORIES`), fake-provider conformance, and contract-level
Forge-style verification. It is frozen as an additive v1 contract under the
same freeze rules. The original 2026-07-30 baseline contracts were not
modified.

## Amendment 2026-10-19

`project-definition.v1` was promoted as an additive, product-neutral Core
contract after bounded implementation acceptance, fresh independent AGY review
with disposition `PASS`, conformance verification, and the separate owner /
architecture promotion decision recorded in
`docs/assurance/PROJECT-DEFINITION-CONTRACT-PROMOTION-DECISION-v1.md`.
The contract is immutable under the normal v1 freeze rules. Consumer adoption,
the candidate Radix agent pipeline, and provider execution remain separately
governed and are not implied by this promotion.

## Explicit exclusions

Runtime, Step 7 qualitative review, `/batch`, worktree isolation and Herdr
implementation are not part of the frozen v1 core.
