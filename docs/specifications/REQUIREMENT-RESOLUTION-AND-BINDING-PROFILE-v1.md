# Requirement Resolution and Governed Binding Profile v1

**Status:** Accepted Step 6 implementation profile
**Date:** 2026-08-25
**Normative dependencies:** Platform Constitution v1, Platform Semantic Model
v1, Platform Contract Model v1, Capability Definition Specification v1,
Compatibility Evaluation Profile v1

## Purpose

This profile defines the bounded Core behavior for deterministic requirement
resolution, candidate admission, policy-input production, and proposed binding
planning. It introduces no contract family and does not change
`capability-definition.v1`.

## Reconciliation result

| Step 6 concept | Disposition | Existing owner |
|---|---|---|
| Effective requirement merge | REUSE | `CapabilityRequirement` + `ResolutionResult` |
| Candidate admission | REUSE | Resolution semantics; `SelectionResult` remains the later explicit selection record |
| Compatibility gate | REUSE | PCM compatibility model + Compatibility Evaluation Profile |
| Policy input package | REUSE | Informative in-process projection of governed inputs; Policy remains independently owned |
| Binding plan | REUSE | Proposed `CapabilityBinding` plus its direct assessed supports |
| Policy decision | REUSE | External governed reference consumed by binding; Step 6 does not define or issue it |

No failed reconciliation proof exists. A new family or relationship type is
therefore prohibited by the Architecture Feature Freeze.

## Boundary

```text
CapabilityRequirement declarations
        ↓
validation and applicability
        ↓
precedence, supersession, and conflict resolution
        ↓
effective requirements + ResolutionResult
        ↓
candidate admission using declared capabilities, conformance,
compatibility, constraints, and currentness
        ↓
policy input package
        ↓
external selection + explicit PolicyDecision
        ↓
proposed CapabilityBinding plan
```

The implementation SHALL NOT execute work, provision resources, deploy an
artifact, activate a binding, infer policy, or use an AI/model heuristic.

## Deterministic requirement resolution

Given byte-equivalent governed inputs, authority configuration, scope,
condition values, method version, and evaluation time, the resolver SHALL emit
the same ordered semantic output.

The resolver:

1. validates every declaration against `capability-definition.v1`;
2. admits only explicitly recognized issuer/authority pairs;
3. admits only exact applicable scope;
4. evaluates declared conditions without fabricating missing values;
5. applies same-issuer explicit supersession and authorized overrides;
6. groups declarations by capability identity;
7. preserves prohibitions and hard requirements;
8. reports equal-authority hard contradictions as unresolved;
9. preserves preferences and optional requirements without promoting them;
10. emits a schema-valid `ResolutionResult` with direct lineage.

Source order, dictionary order, and filesystem order SHALL NOT affect output.
This v1 reference implementation intentionally does not invent authority
hierarchies or scope inheritance. Authority and applicability must be explicit.

## Candidate admission

Candidate admission answers only:

> Which declared implementations remain eligible for this effective
> requirement under the supplied assessments?

An implementation is eligible only when:

- it declares the exact capability reference;
- it is not withdrawn;
- every required conformance dimension is currently `satisfied` under a
  recognized issuer authority;
- every required compatibility assessment is attributable, digest-verified,
  current, scoped, and `compatible`;
- every supplied hard constraint assessment is attributable,
  digest-verified, current, scoped, and satisfied; and
- the requirement is not prohibited or unresolved.

Missing, failed, expired, incompatible, or ambiguous facts reject the candidate
with attributable reason codes. Candidate admission does not select a winner.
Soft preferences MAY be preserved as measurements for later policy or human
decision; they do not authorize selection.

## Policy input package

The policy input package is an in-process projection, not a new public
contract. It contains exact references to:

- the effective requirement and its resolution;
- eligible and rejected candidates;
- conformance claims;
- compatibility assessments;
- evaluated constraints;
- risk references; and
- known unresolved issues and limitations.

It contains no policy outcome.

## Governed proposed binding

Binding planning consumes, but never creates:

- one schema-valid `SelectionResult` with outcome `selected`;
- the selected exact implementation descriptor;
- current satisfied conformance claims;
- compatible assessment references required by the policy input;
- evaluated constraint references;
- an optional risk reference;
- an explicit externally issued `PolicyDecision` whose outcome is `ALLOW`;
- binding issuer authority and exact validity scope.

The planner verifies the supplied facts and emits a schema-valid
`CapabilityBinding` with `lifecycle_status: proposed`. It SHALL NOT emit an
active binding. Activation is a later authorized lifecycle operation.

Compatibility references are preserved in the binding plan's direct supports.
They are not added to the frozen binding schema. The referenced policy decision
is responsible for preserving the evidence it interpreted under its own
contract.

## Fail-closed rules

The implementation rejects or leaves unresolved:

- structurally invalid declarations;
- unrecognized or absent authority;
- out-of-scope requirements or decisions;
- missing condition values;
- invalid or ambiguous supersession;
- required/prohibited contradictions;
- missing or non-satisfied conformance dimensions;
- incompatible, expired, or unknown compatibility;
- failed hard constraints;
- a selection/result mismatch;
- a policy outcome other than `ALLOW`;
- an expired, future-effective, revoked, forged, or out-of-scope policy fact;
- a policy fact not bound to the exact selection; and
- any attempt to create an active binding.

## Exit criteria

- Resolution is deterministic under reordered inputs.
- Hard conflicts remain unresolved and block candidate admission.
- Candidate admission never selects or binds.
- Binding consumes an explicit policy decision and never evaluates policy.
- Only proposed schema-valid bindings are emitted.
- Positive, negative, adversarial, and temporal fixtures pass.
- No schema, constitutional artifact, consumer repository, provider runtime, or
  transport implementation is changed.
