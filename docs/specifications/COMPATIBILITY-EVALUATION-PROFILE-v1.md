# Compatibility Evaluation Profile v1

**Status:** Accepted implementation profile

**Version:** 1.0.0

**Date:** 2026-08-25

**Contract authority:** [Platform Contract Model v1](../constitution/PLATFORM-CONTRACT-MODEL-v1.md)

**Reconciliation authority:** [Contract Reconciliation Matrix v1](../assurance/CONTRACT-RECONCILIATION-MATRIX-v1.md)

## Purpose

This profile defines deterministic compatibility evaluation between two exact,
versioned contract or capability references.

It implements the existing Contract Governance and Compatibility capability
through the Evaluation responsibility. It does not introduce a Compatibility
capability or contract family.

The evaluator answers only:

> What does the admitted evidence establish about interoperability between
> these identified versions in the requested direction and dimensions?

It does not select, authorize, bind, migrate, deploy, execute, or infer trust.

## Inputs

A compatibility evaluation requires:

- exact source identity and version;
- exact target identity and version;
- requested direction: backward, forward, or mutual;
- required compatibility dimensions;
- evaluation time;
- recognized independent evidence issuers and authority bindings; and
- zero or more attributable compatibility evidence candidates.

Version numbers and ranges are identifiers and constraints. They never prove
compatibility by themselves.

## Dimensions

The supported dimensions are:

- structural;
- semantic;
- behavioral; and
- operational.

Each required dimension is evaluated independently.

## Directional evidence results

An admitted evidence candidate reports exactly one of:

- `backward_compatible`;
- `forward_compatible`;
- `mutually_compatible`;
- `incompatible`; or
- `unknown`.

Directional sufficiency is explicit:

| Requested direction | Sufficient evidence result |
|---|---|
| backward | `backward_compatible` or `mutually_compatible` |
| forward | `forward_compatible` or `mutually_compatible` |
| mutual | `mutually_compatible` only |

Evidence for a different direction does not establish incompatibility. It
leaves the requested direction unknown unless evidence explicitly reports
`incompatible`.

## Evidence admission

Every evidence candidate must bind:

- evidence identity and version;
- exact source and target references;
- compatibility dimension and directional result;
- change impact;
- evaluation method and environment;
- complete-envelope digest;
- issuer and recognized authority;
- observation, effectivity, expiry, and revocation times;
- validity scope;
- limitations; and
- explicit supersession where competing evidence is replaced.

Neither source nor target issuer may independently certify compatibility for
its own artifact. A separately recognized evaluator is required.

Missing, malformed, mismatched, forged, not-yet-effective, revoked, ambiguous,
or out-of-scope evidence does not establish compatibility.

## Temporal and conflict rules

- Clock skew is zero unless explicitly configured as a non-negative bound.
- Evidence observed beyond allowed skew is invalid.
- Evidence does not apply before its effective time.
- Expired evidence remains expired.
- Revoked evidence is ineligible.
- Multiple active candidates for one dimension are ambiguous unless one
  attributable same-issuer supersession chain has exactly one head.
- Different issuers cannot silently supersede each other.
- Contradictory active evidence fails closed to unknown.

## Aggregate result

The evaluator retains dimension-specific results and derives a presentation
outcome using this precedence:

```text
incompatible > expired > unknown > compatible
```

`compatible` requires sufficient directional evidence for every required
dimension. The aggregate never replaces its supports and never grants
permission.

## Materialization boundary

Until the reconciled Evaluation family is promoted, the reference
implementation returns an in-process typed assessment and findings. It does
not invent a new public wire contract.

A future Evaluation-family materialization must preserve the exact source,
target, direction, dimensions, evidence supports, issuer, scope, method,
limitations, time, and uncertainty defined here.

## Explicit non-goals

This profile does not:

- infer compatibility from semantic version numbers;
- perform schema migration;
- resolve dependency graphs;
- select an implementation;
- assess risk;
- make a policy decision;
- create or activate a capability binding;
- execute work; or
- modify a consumer repository.
