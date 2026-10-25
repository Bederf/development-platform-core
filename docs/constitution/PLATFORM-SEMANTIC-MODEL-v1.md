# Platform Semantic Model v1

**Status:** Frozen

**Version:** 1.0.0

**Ratified:** 2026-08-25

**Normative authority:** [Development Platform Constitution v1](PLATFORM-CONSTITUTION-v1.md)

## Purpose

The Platform Semantic Model (PSM) defines the irreducible meanings through
which governed platform activity is represented. It is a semantic model, not a
runtime API, storage model, workflow engine, event system, or object ontology.

Every governed platform operation is represented as one or more of:

```text
Declaration
Observation
Resolution
Execution
Evaluation
```

No implementation may introduce an opaque sixth operation while claiming PSM
v1 conformance. A genuinely irreducible new operation requires constitutional
amendment.

## Core terms

| Term | Meaning |
|---|---|
| Semantic object | A typed unit of governed meaning, transient or materialized |
| Semantic operation | One of the five irreducible ways governed meaning is asserted, captured, derived, enacted, or assessed |
| Semantic result | The typed meaning produced by a semantic operation |
| Materialized record | A durable representation of a semantic object or result |
| Direct support | An input, source, or prior result on which a derived result directly depends |
| Method | The declared rules, procedure, criteria, or mechanism governing an operation |
| Validity scope | The bounded subjects, actions, projects, sessions, times, environments, or contract versions for which meaning applies |
| Authority binding | An explicit scoped relationship authorizing an issuer or actor for a subject and action under a contract or policy |

Semantic meaning does not depend on whether a result is stored. Materialization
requirements are determined by contract, policy, lifecycle, audit, evidence,
replay, and interoperability needs.

## Operation 1 — Declaration

### Question

What is asserted, required, intended, or defined?

### Semantics

Declaration introduces governed meaning from an attributable issuer. Examples
include project definitions, capability definitions, requirements, policies,
claims, constraints, evaluation definitions, and architecture decisions.

### Semantic result

`Declaration`

### Optional materialization

`DeclarationRecord`

### Required meaning

A declaration identifies or references:

- issuer;
- semantic type;
- asserted content;
- validity scope;
- governing contract version; and
- claimed authority or authority binding where applicable.

### Non-implication

Declaration does not by itself establish authority. Existence, authorship,
publication, or possession does not make a declaration authoritative outside
an explicit authority binding.

## Operation 2 — Observation

### Question

What was perceived or reported?

### Semantics

Observation captures a bounded perception or report from an attributable
source. An observation may originate from an event, webhook, database, file,
tool, sensor, runtime, user, or another source.

An observation records what the source reported or perceived; it does not
automatically establish the underlying state as true.

### Semantic result

`Observation`

### Optional materialization

`ObservationRecord`

### Required meaning

An observation identifies or references:

- source and observer;
- observed subject;
- observation time when applicable;
- collection method;
- scope;
- uncertainty, quality, or limitations when known; and
- governing semantic or contract version.

### Non-implication

Observation does not by itself establish truth, authority, policy permission,
or evidentiary status.

Runtime events are possible observation sources or transports. Event delivery
does not define observation semantics.

## Operation 3 — Resolution

### Question

What was selected or derived under declared rules?

### Semantics

Resolution transforms governed inputs into governed outputs according to a
declared method while preserving provenance, unresolved alternatives, and
limitations where applicable.

Examples include effective-requirement resolution, capability binding,
implementation selection, context compilation, policy decision, template
rendering, and conflict disposition.

### Semantic result

`Resolution`

### Optional materialization

`ResolutionResult`

### Required meaning

A resolution identifies or references:

- governed inputs and direct supports;
- resolver or issuing authority;
- declared rules or method and version;
- selected, derived, rejected, or unresolved outputs;
- validity scope;
- limitations and uncertainty; and
- lineage to prior semantic results.

### Non-implication

Resolution does not imply permission. A selected provider, implementation,
plan, context bundle, or policy outcome may still require authorization,
evaluation, or an additional lifecycle decision.

## Operation 4 — Execution

### Question

What work or effect was attempted or performed?

### Semantics

Execution represents authorized work, attempted effects, or completed effects.
It applies to deterministic tools, AI-backed providers, build systems, human
work, local processes, remote runtimes, and other conformant implementations.

### Semantic result

`Execution`

### Optional materialization

`ExecutionResult`

### Required meaning

An execution identifies or references:

- authorized request and capability binding;
- actor or implementation;
- subject and scope;
- attempted operation;
- start and completion state when applicable;
- produced outputs and observations;
- failures, cancellations, partial effects, or uncertainty; and
- applicable policy and contract versions.

### Non-implication

Execution does not imply success. Process exit, provider success, artifact
production, or side-effect attempt does not establish that requirements,
claims, policy, or acceptance criteria were satisfied.

## Operation 5 — Evaluation

### Question

How was a subject assessed against declared criteria?

### Semantics

Evaluation assesses a declared subject using an attributable method and
criteria. Methods may be deterministic, statistical, comparative, model-based,
human, or composite.

### Semantic result

`Evaluation`

### Optional materialization

`EvaluationResult`

### Required meaning

An evaluation identifies or references:

- subject and immutable subject identity or digest when applicable;
- evaluation definition and version;
- evaluator or issuer;
- method, criteria, thresholds, and environment;
- findings, measurements, and claim results;
- direct supports;
- limitations, uncertainty, and indeterminate outcomes; and
- validity scope.

### Non-implication

Evaluation does not imply acceptance or authorization. Satisfied claims are
facts available to policy and accountable authority; they are not permission
to merge, release, transition, or execute.

## Symmetric non-implication rules

1. Declaration does not imply authority.
2. Observation does not imply truth.
3. Resolution does not imply permission.
4. Execution does not imply success.
5. Evaluation does not imply acceptance.

Contracts may impose stronger requirements. They SHALL NOT weaken these rules.

## Composition semantics

A governed platform activity may compose multiple semantic operations.
Composition SHALL preserve the type and lineage of every step rather than
collapsing distinct meanings into one generic status.

Examples:

```text
Declaration(requirement)
    → Resolution(implementation binding)
    → Execution(engineering work)
    → Observation(runtime outputs)
    → Evaluation(acceptance criteria)
    → Resolution(policy decision)
```

```text
Observation(source material)
    → Evaluation(admission criteria)
    → Resolution(context compilation)
```

```text
Declaration(human task)
    → Resolution(assignment)
    → Execution(human work)
    → Evaluation(review)
```

The examples are non-normative compositions. The PSM does not require one
sequence, workflow strategy, actor type, or runtime.

## Information properties

Semantic objects are typed, attributable, scoped, logically identifiable,
referenceable, version-governed, lineage-aware when derived, and supersedable
where their semantics permit change.

### Identity

- logical identity;
- semantic type;
- issuer, observer, resolver, actor, or evaluator as applicable;
- explicit authority binding where applicable; and
- validity scope.

### Lineage

- inputs or direct supports;
- provenance;
- governing method;
- semantic and contract versions; and
- relationship to prior and derived results.

### Lifecycle

- creation or operation time;
- observation time when applicable;
- limitations and uncertainty;
- supersession or revocation semantics; and
- materialization and retention obligations where policy requires them.

## Lineage rules

1. Derived results SHALL reference their direct supports.
2. Transitive lineage MAY be reconstructed; it SHALL NOT replace direct-support
   attribution.
3. Transformation SHALL NOT transfer source authority to a derived result.
4. Missing provenance, authority, or uncertainty SHALL remain explicitly
   missing or unknown.
5. Corrections SHALL create an attributable supersession, revocation, or new
   result rather than mutate issued history.
6. A digest MAY establish content identity; it does not establish meaning,
   authority, quality, or acceptance.

## Observation, evidence, and policy

Observation, evidence, and policy are distinct:

```text
Source occurrence
    → Observation
    → Evaluation or evidence admission
    → Evidence support
    → Policy resolution
    → Authorization decision
```

Not every observation becomes evidence. Evidence records identify which
observations or other supports were admitted, for which claim or decision, by
which method, and within which scope.

Policy resolution consumes governed inputs and produces a decision. Policy
SHALL NOT modify the observations, evaluations, attestations, or evidence it
interprets.

## Materialization

The PSM does not require universal persistence. Contracts and policy determine
whether semantic results are transient, cached, retained, replayable, or
durably recorded.

When materialized, a record SHALL preserve the meaning and information
properties of its semantic result. Serialization, database schema, file layout,
event format, and transport are implementation concerns governed by contract
families beneath the PSM.

## Compatibility

Changes to operation meaning, required information properties,
non-implication rules, or composition semantics are constitutional changes.
They require coordinated amendment of the Constitution and PSM.

Adding a specialized contract record beneath an existing semantic operation
does not require constitutional amendment when it preserves PSM meaning and
passes contract compatibility rules.

## Explicit exclusions

The PSM does not define:

- agents, prompts, models, memory, RAG, or reasoning;
- workflow or orchestration strategy;
- events, queues, schedulers, or state stores;
- providers, registries, discovery protocols, or adapters;
- databases, files, APIs, SDKs, MCP, or network transports;
- evaluation algorithms, policy languages, or execution runtimes; or
- application-domain ontology.
