# ReviewCycle v1

Status: candidate contract, qualified by fake-provider conformance tests.

## Purpose

`review-cycle.v1` records one bounded pass through implementation revision,
independent review, and the resulting GSD next action. It is coordination
state, not a new authority and not a copy of any underlying review or finding.

The record references the existing `ReviewResult`, finding, evidence,
revision, and Forge verification records by identifier.

## Invariants

- `cycle_number` is 1, 2, or 3 and `max_cycles` is always 3.
- A cycle is tied to exactly one implementation `revision_ref` and one
  `review_result_ref`.
- Finding identifiers are references. The findings themselves remain durable
  across later revisions and cycles.
- Every cycle has at least one evidence reference.
- Completion checks compare implementation closure records against the canonical
  mandatory requirement set; omitted or invented requirement identifiers fail.
- `PASS` leads to `forge_verify`; it never means the task is complete.
- `CHANGES_REQUIRED` keeps the cycle open and requires at least one finding.
- A third unsuccessful cycle cannot create a fourth revision automatically;
  it must stop or escalate.
- Incomplete, blocked, and escalated review outcomes cannot advance to Forge.

## Lineage

The chain is represented without duplicating records:

```text
task_ref
  └─ revision_ref (cycle 1)
       └─ review_result_ref
            └─ finding_refs
                 └─ revision_ref (cycle 2, prior_cycle_ref = cycle 1)
```

The next revision is recorded by the next cycle's `revision_ref`; the current
cycle's `next_revision_ref` is only a forward reference to that known revision.

## Completion boundary

GSD remains responsible for deciding whether work may complete. Completion
requires focused tests, no unresolved blockers, and independent Forge
verification. A valid `PASS` ReviewCycle is therefore necessary evidence for
the workflow but is not sufficient completion authority.

## Out of scope

This contract does not execute coding agents, invoke reviewers, perform
retries, resolve providers, authorize changes, or replace `delegation.v1`.
Those concerns require separately qualified contracts and implementations.
