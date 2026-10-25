# Development Workflow Contract v1

Status: promoted v1 contract. Provider-neutral. No provider adapter is
authorized by this document.

## Purpose

This contract defines the canonical lifecycle for turning human intent into an
accepted implementation. It governs artifacts, authority, evidence, and state
transitions; it does not prescribe a coding tool, model, repository layout, or
runtime implementation.

The wire shape is [`development-workflow.v1`](../../contracts/development-workflow.v1.schema.json).

## Lifecycle

```text
INTENT → SPECIFICATION → ASSESSMENT → PLAN → TASKS → IMPLEMENTATION
        → VERIFICATION → CONVERGENCE → ACCEPTANCE
                                      ├─ failure → REMEDIATION → IMPLEMENTATION
                                      └─ success → ACCEPTANCE
```

`VERIFICATION` is independent of the implementation producer. `CONVERGENCE`
assesses whether the implementation and verification evidence satisfy the
approved specification, plan, and task set; it is not itself authoritative
verification and cannot by itself establish acceptance.

## Required artifacts

Each stage produces a versioned, content-addressed artifact with a stable
reference, producer identity, creation time, and lineage to prior artifacts.
The required kinds are: intent, specification, assessment, plan, task list,
implementation record, verification result, convergence assessment, and
acceptance record. Providers may store or render these artifacts differently,
but the contract requires their references and relationships to remain
recoverable.

## Authority and gates

- A provider may propose artifacts and transitions but cannot grant itself
  authority.
- Advancement requires the gate applicable to the target stage.
- A gate records its decision-maker and evidence references.
- `REJECTED`, `RETURNED`, `BLOCKED`, and `CANCELLED` work cannot be represented
  as accepted work.
- Acceptance requires approved requirements, completed traceability, passing
  independent verification, and a successful convergence assessment.
- Unavailable, failed, or incomplete verification returns work for remediation
  or blocks acceptance.

## Failure and return semantics

Returned work preserves the prior artifacts and creates a new revision linked
through `supersedes_ref`. A provider must not overwrite history to hide an
attempt, failure, rejection, or missing evidence. Remediation creates new
tasks or revisions and must pass verification again before acceptance.

## Scope exclusions

This v1 contract does not define agent execution, batch or worktree
orchestration, transport, provider selection, implementation extraction, or
consumer-specific workflow semantics. Those concerns require separately
versioned contracts.
