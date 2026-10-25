# Platform Contract Model v1

**Status:** Frozen

**Version:** 1.0.0

**Ratified:** 2026-08-25

**Constitutional authority:** [Development Platform Constitution v1](PLATFORM-CONSTITUTION-v1.md)

**Semantic authority:** [Platform Semantic Model v1](PLATFORM-SEMANTIC-MODEL-v1.md)

## Purpose

The Platform Contract Model (PCM) defines how governed meaning is represented
and exchanged between independent Development Platform implementations.

The Constitution defines governing truth. The PSM defines meaning and semantic
operations. The PCM defines versioned interaction and representation without
prescribing serialization, transport, storage, programming language, service
architecture, provider, or application design.

The key words **SHALL**, **SHALL NOT**, **SHOULD**, and **MAY** are normative.

## Scope

The PCM governs:

- contract-family identity and ownership;
- normative and informative content;
- semantic-operation mapping;
- materialized record envelopes;
- versioning and compatibility;
- lifecycle and supersession;
- conformance claims;
- cross-contract references; and
- transport-neutral interaction semantics.

The PCM is a meta-model. It does not itself define project, capability,
evaluation, evidence, lifecycle, workflow, tool, or provider payload schemas.

## Contract model

A platform contract is a versioned declaration of governed semantics and
interoperability expectations.

A contract definition SHALL identify or reference:

```text
contract family identity
contract identity and version
normative owner
semantic purpose and scope
Platform Semantic Model operation mapping
normative fields and constraints
informative annotations
compatibility policy
lifecycle status
conformance requirements
supersession or replacement relationship
```

Every field exists for one of two explicit purposes:

1. **Normative:** consumed by validation, resolution, evaluation, policy,
   binding, lifecycle, or another governed operation.
2. **Informative:** assists human understanding but SHALL NOT alter machine
   decisions.

An implementation SHALL NOT derive normative behavior from informative text.
If machine-consumed text affects behavior, it is normative contract content and
is governed accordingly.

## Contract families

A contract family groups records that share one coherent semantic domain and
versioning policy. Family membership SHALL NOT erase the semantic type of an
individual record.

A family definition identifies or references:

- stable family identity;
- normative owner;
- included semantic types;
- allowed cross-family references;
- compatibility and deprecation policy;
- shared information properties;
- conformance profile; and
- amendment history.

Contract families evolve independently unless an explicit dependency requires
coordinated versioning.

## Semantic-operation mapping

Every normative contract operation SHALL map to one or more PSM operations:

- Declaration;
- Observation;
- Resolution;
- Execution; or
- Evaluation.

The mapping preserves non-implication rules. A result schema SHALL NOT collapse:

- declaration into authority;
- observation into truth or evidence;
- resolution into permission;
- execution into success; or
- evaluation into acceptance.

Composite contracts MAY carry multiple typed semantic results. Each result
retains its operation type and lineage.

## Information and record requirements

All semantic objects satisfy the Constitution's information properties. When a
contract materializes a record, it SHALL define how the record carries or
references applicable identity, authority, lineage, lifecycle, limitation, and
version information.

A shared envelope MAY standardize recurring fields. It SHALL NOT replace typed
contract semantics with an unbounded generic object.

Missing identity, provenance, authority, support, uncertainty, or scope SHALL
remain explicitly missing, unknown, or invalid according to contract policy. A
normalizer SHALL NOT fabricate those values.

## Interaction pattern

Contracts MAY define declarations, requests, results, observations, claims,
decisions, transitions, or references. When an interaction has request/result
semantics, it SHALL preserve:

- request identity;
- result identity;
- explicit correlation;
- operation identity or attempt identity when retries are possible;
- actor and issuer identity;
- applicable contract versions;
- typed failure, cancellation, unknown, and partial outcomes; and
- lineage to produced artifacts or evidence when applicable.

Matching session identity alone is insufficient correlation when multiple
operations can occur within one session.

Contracts SHALL distinguish an accepted request from a completed operation and
a completed operation from an evaluated successful outcome.

## Version model

Every public contract and contract family SHALL have an explicit semantic
version.

### Version impact

| Change class | Minimum treatment |
|---|---|
| Editorial informative correction | Patch |
| Backward-compatible normative addition | Minor |
| Changed default, interpretation, required behavior, or removed semantic support | Major unless compatibility evidence proves otherwise |
| Changed PSM operation meaning or constitutional invariant | Constitutional amendment and coordinated release |

Version numbers do not prove compatibility. Compatibility is an assessed,
directional relationship between identified versions.

## Compatibility model

Compatibility has separate dimensions:

- structural;
- semantic;
- behavioral; and
- operational where environment-dependent execution is relevant.

A compatibility assessment SHALL identify or reference:

```text
source contract and version
target contract and version
direction
assessed dimensions
assessment method
result per dimension
evidence supports
issuer
limitations
assessment time and validity
```

Allowed directional results are:

- backward compatible;
- forward compatible;
- mutually compatible;
- incompatible; or
- unknown.

Change impact is recorded separately as editorial, additive, behavioral, or
breaking.

Lifecycle status is also separate:

- experimental;
- stable;
- deprecated; or
- withdrawn.

Experimental or deprecated status does not itself establish compatibility or
incompatibility.

## Conformance model

Conformance is claim-based and multidimensional. `Declared` is not a
conformance result, and governance eligibility is not technical conformance.

Supported dimensions include:

- structural;
- semantic;
- behavioral; and
- operational.

Each dimension uses explicit outcomes such as:

- satisfied;
- failed;
- unknown; and
- expired where time-bound evidence applies.

A conformance claim SHALL identify or reference:

- subject implementation and immutable version or digest;
- target contract, capability, and profile versions;
- conformance dimension;
- method and environment;
- direct evidence supports;
- issuer;
- assessment time and validity or expiry;
- limitations; and
- supersession or revocation.

A bare `PASS` without attributable evidence is invalid.

Policy may resolve governance eligibility as allowed, denied,
review-required, conditional, or another versioned policy result. That decision
references conformance claims; it does not modify them.

## Cross-contract relationships

Relationships SHALL declare their source type, target type, meaning,
cardinality where relevant, and compatibility expectations.

A cross-contract reference SHALL identify the target contract family and
version range or exact version required by the referencing contract.

Relationships that describe dependency, implementation claims, conformance,
supersession, or binding history SHALL remain distinct. A generic untyped
`related_to` relationship is insufficient for governed resolution.

## Authority and policy

A schema-valid contract record is not automatically authoritative. Authority
is established through the Constitution's explicit authority-binding model.

Contracts declare where policy decisions are required. They do not embed
provider-specific authorization or assume that validation grants permission.

## Failure and uncertainty

Contracts SHALL represent material failure and uncertainty explicitly. They
SHALL NOT map:

- unavailable to empty;
- unknown to false;
- indeterminate to pass;
- partial to complete;
- timeout to success; or
- missing evidence to satisfied.

Degraded behavior is contract-defined and visible. Silent fallback that changes
semantic meaning is non-conformant.

## Serialization and transport

JSON Schema, YAML, protocol buffers, database schemas, files, APIs, CLIs, SDKs,
MCP, queues, and in-process types are possible representations or transports.
None is constitutional or required by the PCM.

A generated schema or validator is conformant only when it preserves the
normative contract semantics. Schema validity is necessary but not sufficient
for semantic, behavioral, or operational conformance.

## Legacy frozen v1 contracts

Contracts frozen before PCM v1 retain their identifiers, schemas, accepted
semantics, and freeze rules. PCM v1 SHALL NOT retroactively invalidate them for
lacking fields introduced by this meta-model.

Each legacy contract must be mapped as:

- `REUSE`;
- `EXTEND` through a new compatible version;
- `NEW_FAMILY`; or
- `REJECT` for the proposed responsibility.

No frozen contract is renamed or amended in place. New contract work applies
PCM v1 unless an explicit evidence-led decision records a bounded exception.

## Contract-definition readiness

A proposed contract is ready for schema work only when:

1. semantic purpose and non-purpose are explicit;
2. PSM operation mapping is complete;
3. normative and informative fields are separated;
4. ownership and authority boundaries are explicit;
5. existing-contract reconciliation is recorded;
6. compatibility and lifecycle policy are defined;
7. conformance claims and evidence requirements are defined;
8. negative and unknown outcomes are specified;
9. fake-provider or fake-implementation fixtures are designed; and
10. no consumer-specific field or branch is required.

## Evolution

PCM v1 is stable but independently versioned beneath the Constitution and PSM.
It MAY evolve without a constitutional amendment when changes preserve
constitutional axioms, PSM operation meanings, and compatibility guarantees.

A PCM change that alters constitutional truth or PSM meaning requires the
constitutional amendment process.
