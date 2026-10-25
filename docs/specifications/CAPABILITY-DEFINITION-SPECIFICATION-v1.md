# Capability Definition Specification v1

**Status:** Accepted — schema authority

**Version:** 1.0.0

**Date:** 2026-08-25

**Contract authority:** [Platform Contract Model v1](../constitution/PLATFORM-CONTRACT-MODEL-v1.md)

**Semantic authority:** [Platform Semantic Model v1](../constitution/PLATFORM-SEMANTIC-MODEL-v1.md)

**Capability authority:** [Capability Model v1](../constitution/CAPABILITY-MODEL-v1.md)

**Acceptance authority:** User instruction to continue with Step 4 on
2026-08-25 after Gates 1–3 passed

## Purpose

This specification defines the logical, machine-actionable model for declaring,
requiring, relating, profiling, resolving, evaluating, and binding platform
capabilities.

It is intended to become the normative source for future:

- schemas;
- validators;
- requirement reconciliation;
- dependency and conflict resolution;
- conformance evaluation;
- composition planning;
- documentation generation; and
- guided bootstrap planning.

This specification is the normative semantic source for the versioned
Capability Definition contract family. Derived schemas must preserve it. It
does not implement a registry, resolver, conformance engine, bootstrap planner,
runtime, or provider.

## Normative and informative content

Every field defined by this specification is classified as:

- **normative:** consumed by a governed validator, resolver, evaluator, policy,
  binding, lifecycle, or compatibility operation; or
- **informative:** human-facing annotation that SHALL NOT change a machine
  decision.

Machine-consumed descriptions are normative even when encoded as text.
Informative rationale MAY exist, but engines SHALL ignore it when determining
validity, compatibility, conformance, selection, or authorization.

## Logical document family

The accepted family includes:

```text
CapabilityDefinition
CapabilityProfile
CapabilityRelationship
CapabilityRequirement
ImplementationDescriptor
SelectionResult
ResolutionResult
ConformanceClaim
CapabilityBinding
ConstraintReference
RiskAssessmentReference
```

The entities are represented by one coherent `capability-definition.v1`
contract family with an explicit `entity_type` discriminator. Packaging them
together does not merge their semantic responsibilities.

Field-level disposition and representation decisions are recorded in
[Capability Definition Field Reconciliation v1](../assurance/CAPABILITY-DEFINITION-FIELD-RECONCILIATION-v1.md).

## Common types

### Stable identifier

A stable identifier is lowercase, globally unique within its declared
namespace, and independent of implementation name or deployment location.

Recommended canonical form:

```text
namespace.capability-name
```

Renaming an identifier is a replacement or supersession, not an editorial
change.

### Version

Public definitions use semantic versions. Version ranges are explicit and
SHALL NOT imply compatibility without a compatibility assessment.

### Reference

A governed reference identifies:

- semantic type;
- stable identifier;
- exact version or allowed version range;
- issuer or namespace where ambiguity is possible; and
- digest when immutable content identity is required.

### Result status

Statuses distinguish at least:

- satisfied;
- failed;
- unknown;
- unresolved;
- conditional; and
- expired where evidence is time-bound.

Unknown, unresolved, and expired SHALL NOT be treated as satisfied.

### Shared family representation

Every materialized family entity carries:

- `schema`, fixed to `capability-definition.v1`;
- an exact `entity_type`;
- its entity-specific stable identity;
- `issuer`;
- explicit `authority_binding` where authority is claimed;
- `validity_scope`;
- `supersession` where lifecycle applies; and
- optional `informative` annotations that SHALL NOT affect governed decisions.

## CapabilityDefinition

`CapabilityDefinition` is a PSM Declaration describing one stable
responsibility independently of implementation form.

### Required normative fields

| Field | Meaning | Primary consumer |
|---|---|---|
| `schema` | Capability-definition contract identity and version | Validator |
| `entity_type` | Exact logical entity discriminator | Validator |
| `capability_id` | Stable capability identity | All engines |
| `version` | Definition semantic version | Compatibility evaluator |
| `lifecycle_status` | Experimental, stable, deprecated, or withdrawn | Resolver and policy |
| `classification` | Platform-baseline or optional | Composition planner |
| `semantic_description` | Normative meaning of the responsibility | Semantic conformance evaluator |
| `responsibilities` | Positive responsibility statements | Resolver and conformance evaluator |
| `non_responsibilities` | Explicit ownership exclusions | Conflict and semantic evaluation |
| `semantic_operations` | PSM operations the capability may perform | Validator and policy |
| `input_contracts` | Accepted typed inputs and versions | Validator and compatibility evaluator |
| `output_contracts` | Produced typed results and versions | Validator and compatibility evaluator |
| `relationships` | Typed capability relationships | Dependency resolver |
| `profiles` | Supported capability profiles | Profile resolver |
| `policy_requirements` | Policy decision points and references | Policy evaluator |
| `constraint_requirements` | Constraint definitions applicable to binding or execution | Constraint evaluator |
| `conformance_requirements` | Required conformance dimensions and claims | Conformance evaluator |
| `compatibility_policy` | Definition evolution and profile compatibility rules | Compatibility evaluator |
| `issuer` | Attributable definition issuer | Admission and authority evaluation |
| `authority_binding` | Scope of issuer authority | Admission and policy |
| `validity_scope` | Where the definition applies | Resolver and policy |
| `supersession` | Prior definition replaced or revoked | Lifecycle and compatibility |

### Optional informative fields

- summary;
- rationale;
- examples;
- documentation references;
- display labels; and
- presentation metadata.

Informative fields SHALL NOT alter resolution or conformance.

### Validation rules

1. `capability_id` and `version` form the definition identity.
2. At least one responsibility is required.
3. Responsibilities and non-responsibilities SHALL NOT contradict each other.
4. Every input and output references a versioned contract.
5. Every relationship uses an allowed source and target type.
6. Every semantic operation is defined by PSM v1.
7. A withdrawn definition is ineligible for a new binding unless explicit
   policy and compatibility rules allow a bounded exception.
8. Missing authority or validity scope is invalid where the definition claims
   platform or organization authority.

## Capability profiles

A `CapabilityProfile` strengthens, narrows, or specializes conformance
requirements without changing capability identity.

Profiles describe semantics, not vendors or products.

Examples of semantic profiles for a knowledge capability might include:

- structured query;
- lexical retrieval;
- semantic retrieval; and
- hybrid retrieval.

Filesystem, SQL products, graph databases, and vector databases are
implementations or implementation characteristics unless a separate semantic
profile is justified.

### Required profile fields

| Field | Meaning |
|---|---|
| `profile_id` | Stable identity within the capability |
| `version` | Profile version |
| `semantic_description` | Normative specialization |
| `base_capability` | Exact capability identity and compatible range |
| `additional_responsibilities` | Responsibilities added by the profile |
| `additional_constraints` | Constraints added or strengthened |
| `input_contracts` | Additional or narrowed accepted inputs |
| `output_contracts` | Additional or narrowed produced results |
| `conformance_requirements` | Profile-specific conformance claims |
| `compatibility_policy` | Profile evolution rules |

A profile SHALL NOT weaken the base capability's required responsibilities,
policy points, security boundaries, or conformance requirements. A semantic
change that does so requires a separate capability or new major version.

## Typed capability relationships

Relationship semantics are type-constrained.

### Capability-definition relationships

| Relationship | Source | Target | Meaning |
|---|---|---|---|
| `REQUIRES` | Capability or profile | Capability or profile | Target is mandatory for the source responsibility |
| `OPTIONALLY_USES` | Capability or profile | Capability or profile | Target may enhance the source but absence does not invalidate it |
| `CONFLICTS_WITH` | Capability, profile, or requirement | Capability, profile, or requirement | Both cannot be simultaneously satisfied within the declared scope |
| `EXTENDS` | Capability definition | Capability definition | Source adds compatible responsibility without weakening target semantics |

### Implementation and lifecycle relationships

| Relationship | Source | Target | Meaning |
|---|---|---|---|
| `DECLARES_PROVIDES` | Implementation | Capability/profile | Unverified implementation claim |
| `CONFORMS_TO` | Conformance claim | Implementation and capability/profile versions | Evidence-backed assessed relationship |
| `SUPERSEDES` | Versioned definition or implementation | Earlier compatible identity | New governed version replaces earlier meaning or implementation |
| `REPLACES_BINDING` | Binding | Earlier binding | New binding replaces an earlier scoped association |

`PROVIDES` or `IMPLEMENTS` SHALL NOT be accepted as self-certifying
relationships. Declaration and conformance remain separate.

### Required relationship fields

| Field | Meaning |
|---|---|
| `relationship_id` | Stable materialized relationship identity |
| `relationship_type` | One of the eight relationship types above |
| `source` | Typed, versioned source reference |
| `targets` | One or more typed, versioned target references |
| `cardinality` | Declared target cardinality |
| `compatibility_expectations` | Applicable compatibility policy references |
| `issuer` | Relationship issuer |
| `authority_binding` | Issuer authority for this relationship and scope |
| `validity_scope` | Scope in which the relationship applies |
| `supersession` | Prior relationship replaced or revoked |

Relationship meaning is fixed by `relationship_type`. Free-form record text
cannot redefine it.

## CapabilityRequirement

`CapabilityRequirement` is a PSM Declaration from a project, template,
organization, policy package, deployment profile, or authorized override.

### Required normative fields

| Field | Meaning |
|---|---|
| `requirement_id` | Stable declaration identity |
| `capability` | Required capability and allowed versions |
| `profile_requirements` | Required, allowed, preferred, or prohibited profile references with explicit disposition |
| `strength` | Required, prohibited, preferred, optional, or conditional |
| `issuer` | Requirement issuer |
| `authority_binding` | Authority for this requirement and scope |
| `source_class` | Project, template, organization, policy package, deployment profile, or override |
| `validity_scope` | Applicable project, environment, session, or operation scope |
| `conditions` | Typed predicates for conditional requirements |
| `constraints` | Constraint references |
| `policy_requirements` | Required decisions or approval points |
| `compatibility_expectations` | Allowed versions and compatibility dimensions |
| `supersession` | Requirement replaced, revoked, or overridden |

An optional numeric preference weight MAY rank soft preferences after all hard
requirements are satisfied. It SHALL NOT override authority, prohibition,
mandatory requirements, policy, compatibility, or hard constraints.

## Requirement precedence and conflict semantics

Reconciliation is a deterministic PSM Resolution operation.

The resolver applies this order:

1. validate declaration structure and contract versions;
2. validate issuer authority and requirement applicability;
3. remove expired, superseded, or out-of-scope declarations while preserving
   their history;
4. apply explicit authorized overrides;
5. enforce prohibitions and mandatory requirements;
6. apply scope specificity where authority is otherwise equal;
7. detect unresolved contradictions;
8. evaluate compatibility and hard constraints;
9. rank candidates using soft preferences only; and
10. emit effective requirements, conflicts, rejected inputs, and unresolved
    outcomes with direct lineage.

The resolver SHALL NOT:

- infer authority from source order;
- convert a preference into a mandatory requirement;
- sacrifice a hard requirement to improve a soft preference;
- silently select between equally authoritative contradictions; or
- discard losing declarations from lineage.

An unresolved hard conflict blocks a conformant binding.

## ImplementationDescriptor

`ImplementationDescriptor` is a PSM Declaration of what an implementation
claims to provide. It is not conformance evidence.

### Required descriptor fields

| Field | Meaning |
|---|---|
| `implementation_id` | Stable implementation identity |
| `version` | Immutable implementation version |
| `digest` | Optional immutable content digest |
| `lifecycle_status` | Experimental, stable, deprecated, or withdrawn |
| `roles` | Library, plugin, process, service, runtime, provider, adapter, cluster, or compile-time roles |
| `declared_capabilities` | `DECLARES_PROVIDES` capability/profile references |
| `supported_contracts` | Claimed supported contract versions |
| `operating_constraints` | Applicable constraint references |
| `resource_characteristics` | Typed declared resource characteristics |
| `required_capabilities` | External capability dependencies |
| `credential_references` | Opaque credential references without secret values |
| `compatibility_declarations` | Unverified compatibility declaration references |
| `issuer` | Descriptor issuer |
| `authority_binding` | Issuer authority and scope |
| `validity_scope` | Applicable scope |
| `supersession` | Prior descriptor replaced or revoked |

Runtime, provider, library, plugin, process, service, and adapter are possible
roles. They are not a mandatory dependency chain.

## SelectionResult

Selection is a specialized PSM Resolution, not a sixth semantic operation.

### Required selection fields

| Field | Meaning |
|---|---|
| `selection_id` | Stable Resolution identity |
| `requirement` | Effective capability requirement |
| `eligible_candidates` | Candidates admitted before ranking |
| `method` | Selection method and version |
| `evaluated_constraints` | Hard constraints and soft preferences assessed |
| `outcome` | Selected, unresolved, or no-candidate |
| `selected_candidate` | Selected implementation or explicit null |
| `rejected_candidates` | Candidates and attributable rejection reasons |
| `unresolved` | Remaining alternatives or conflicts |
| `direct_inputs` | Direct governed input lineage |
| `issuer` | Selection issuer |
| `limitations` | Known uncertainty and exclusions |
| `validity_scope` | Scope of the selection result |
| `supersession` | Prior result replaced or revoked |

Selection does not imply conformance, permission, or binding.

## ResolutionResult

`ResolutionResult` materializes a PSM Resolution that is not candidate
selection, including deterministic requirement merge and conflict disposition.

### Required resolution fields

| Field | Meaning |
|---|---|
| `resolution_id` | Stable Resolution identity |
| `resolution_kind` | Versioned kind of resolution performed |
| `inputs` | Direct governed inputs |
| `method` | Resolution method and version |
| `derived_outputs` | Effective or derived results |
| `rejected_inputs` | Inputs rejected with attributable reasons |
| `unresolved` | Conflicts or alternatives left unresolved |
| `issuer` | Resolution issuer |
| `limitations` | Known uncertainty and exclusions |
| `validity_scope` | Scope of the resolution result |
| `supersession` | Prior result replaced or revoked |

A `ResolutionResult` has no permission or authorization field. Policy Decision
remains a separate Resolution referenced where required.

## ConformanceClaim

Conformance is multidimensional and evidence-backed.

### Dimensions

- structural;
- semantic;
- behavioral; and
- operational.

### Outcomes

- satisfied;
- failed;
- unknown; and
- expired for time-bound evidence.

`Declared` is not a conformance outcome. Governance eligibility is a separate
policy resolution.

### Required claim fields

| Field | Meaning |
|---|---|
| `claim_id` | Stable claim identity |
| `subject` | Implementation identity and immutable version or digest |
| `capability` | Capability and profile versions assessed |
| `contracts` | Contract versions assessed |
| `dimension` | Structural, semantic, behavioral, or operational |
| `outcome` | Satisfied, failed, unknown, or expired |
| `method` | Evaluation definition and version |
| `environment` | Relevant execution or assessment environment |
| `supports` | One or more direct EvidenceRecord references |
| `issuer` | Claim issuer |
| `assessment_time` | When assessment occurred |
| `validity` | Scope and expiry where applicable |
| `limitations` | Known gaps, uncertainty, or exclusions |
| `supersession` | Prior claim revoked or replaced |

A satisfied claim without at least one attributable evidence support is
invalid.

A summary conformance level MAY be derived for presentation. Engines SHALL
retain and evaluate the underlying dimension-specific claims.

## Constraints and resources

Resources are constraint dimensions, not a constitutional capability.

Constraint references may cover:

- compute and accelerator needs;
- storage;
- concurrency and quotas;
- latency;
- budget;
- security classification;
- licensing;
- jurisdiction and geography;
- compliance;
- availability; and
- approval requirements.

### Required constraint-reference fields

| Field | Meaning |
|---|---|
| `constraint_reference_id` | Stable reference-record identity |
| `constraint` | Constraint model and version |
| `subject` | Subject constrained |
| `strength` | Hard or soft |
| `issuer` | Constraint-reference issuer |
| `authority_binding` | Issuer authority and scope |
| `evaluation_method` | Method used to evaluate satisfaction |
| `validity_scope` | Applicable scope |
| `valid_until` | Explicit expiry or null |
| `supersession` | Prior reference replaced or revoked |

A satisfied constraint is not authorization.

## RiskAssessmentReference

Risk influences governance but is not permission.

### Required risk-reference fields

| Field | Meaning |
|---|---|
| `risk_reference_id` | Stable reference-record identity |
| `assessment` | Referenced assessment identity and version |
| `subject` | Assessed subject |
| `risk_model` | Risk method/profile and version |
| `hazards` | Identified hazards or threats |
| `inherent_risk` | Profile-defined inherent rating |
| `controls` | Controls included in the assessment |
| `residual_risk` | Profile-defined residual rating |
| `uncertainty` | Known uncertainty and limitations |
| `issuer` | Assessment-reference issuer |
| `authority_binding` | Issuer authority and scope |
| `supports` | Non-empty evidence references |
| `assessment_time` | Assessment time |
| `valid_until` | Expiry or null |
| `validity_scope` | Applicable scope |
| `supersession` | Prior reference replaced or revoked |

Low, moderate, high, and critical MAY be supplied by a versioned risk profile;
they are not universal constitutional values.

## CapabilityBinding

A binding is a governed association between one effective requirement and one
conformant implementation within a validity scope.

### Required binding fields

| Field | Meaning |
|---|---|
| `binding_id` | Stable binding identity |
| `requirement` | Effective capability requirement |
| `capability` | Exact capability and profile versions |
| `implementation` | Exact implementation version or digest |
| `contracts` | Selected contract versions |
| `selection_result` | Resolution that selected the candidate |
| `conformance_claims` | Current required dimension-specific claims |
| `constraints` | Evaluated hard and soft constraints |
| `risk_assessment` | Required risk reference where policy applies |
| `policy_decision` | Explicit binding authorization |
| `issuer` | Binding issuer |
| `authority_binding` | Authority to establish the association |
| `validity_scope` | Project, environment, session, or operation scope |
| `lifecycle_status` | Proposed, active, suspended, superseded, revoked, or expired |
| `supersession` | Binding replaced or revoked |

A binding is invalid when required conformance evidence is missing, failed,
unknown, expired, out of scope, or incompatible unless an explicit policy
defines a bounded review or conditional state. Conditional does not mean
fully conformant.

## Compatibility semantics

Capability definitions, profiles, implementations, contracts, and bindings use
the PCM compatibility model.

Compatibility direction, assessed dimensions, change impact, and lifecycle
status remain separate. Version ranges do not replace compatibility evidence.

An `EXTENDS` relationship requires semantic compatibility evidence. A profile
change that weakens base requirements is breaking.

## Machine consumers

Every normative field has an intended consumer:

| Consumer | Consumed semantics |
|---|---|
| Requirement validator | Structure, types, versions, authority fields, strength, conditions |
| Dependency resolver | `REQUIRES`, `OPTIONALLY_USES`, `CONFLICTS_WITH`, `EXTENDS` |
| Conflict analyzer | Authority, scope, strength, overrides, constraints, compatibility |
| Candidate selector | Effective requirements, profiles, implementation declarations, preferences |
| Conformance evaluator | Capability/profile requirements, methods, evidence, dimensions |
| Policy evaluator | Authority, conformance claims, constraints, risk, requested binding |
| Bootstrap planner | Authorized bindings, provisioning requirements, readiness state |
| Documentation generator | Normative definitions plus explicitly informative annotations |

No normative field exists solely for presentation.

## Deterministic composition-planner boundary

A future planner consumes confirmed declarations rather than raw conversation.

```text
Conversation or questionnaire
    → proposed requirement declarations
    → accountable confirmation
    → validation
    → precedence and conflict resolution
    → candidate compositions
    → compatibility, constraint, cost, and risk evaluation
    → policy decision
    → human selection where required
    → capability bindings
    → bootstrap plan
```

AI may propose declarations or candidates. It SHALL NOT silently create
authoritative requirements, conformance claims, policy decisions, or bindings.

## Existing-contract reconciliation

Before schema work, candidate fields and entities require mapping against the
current Core inventory:

| Existing contract | Required reconciliation focus |
|---|---|
| `development-platform.v1` | Project requirement-source semantics and current capability selections |
| `agent-startup-context.v1` | Specialized context inputs and capability metadata |
| `startup-context-projection.v1` | Bounded projection and lineage semantics |
| `repository-intelligence.v1` | Provider declaration, trust, freshness, and evidence |
| `agent-adapter.v1` | Implementation declaration and provider translation |
| `forge-adapter.v1` | Evaluation/evidence implementation boundary |
| `verification-result.v1` | Conformance outcome and evidence support semantics |
| `gsd-planning-lifecycle.v1` | Conditional planning and lifecycle relationships |
| `gsd-session-governance.v1` | Requirement authority, lifecycle, and execution scope |
| `agent-runtime.v1` | Implementation descriptor, execution, observation, and artifacts |
| `multi-instance-provider.v1` | Constraints, topology, lifecycle, health, and credentials |
| `code-humanizer.v1` | Specialized capability request, artifact, and evaluation relationship |

Entity-level reconciliation is complete in
[Contract Reconciliation Matrix v1](../assurance/CONTRACT-RECONCILIATION-MATRIX-v1.md).
Field-level reconciliation is complete in
[Capability Definition Field Reconciliation v1](../assurance/CAPABILITY-DEFINITION-FIELD-RECONCILIATION-v1.md).
Frozen contracts are not renamed or modified in place.

## Required negative fixtures

Before schema or engine implementation, fixtures SHALL cover:

- duplicate capability identity;
- unknown semantic operation;
- contradictory responsibility and non-responsibility;
- invalid relationship source or target type;
- profile weakening its base capability;
- provider self-certifying `CONFORMS_TO`;
- satisfied conformance claim without evidence;
- expired operational evidence;
- incompatible contract versions;
- prohibited and required capability conflict;
- equally authoritative unresolved requirements;
- soft preference attempting to override a hard constraint;
- selection incorrectly treated as authorization;
- unknown result treated as satisfied;
- binding without policy authorization;
- binding with out-of-scope authority;
- superseded definition selected without exception; and
- missing provenance fabricated by normalization.

## Acceptance record

| Gate | Result | Evidence |
|---|---|---|
| Every entity and field reconciled | PASS | Gate 1 matrix and field-level reconciliation v1 |
| Two independent non-consumer-specific examples | PASS | Static-library and robotics-controller examples |
| Fake-implementation positive and negative fixtures | PASS | Gate 3 fixture corpus and coverage v1 |
| Compatibility and lifecycle rules complete | PASS | PCM v1, relationship rules, binding lifecycle, expiry and supersession fixtures |
| Deterministic precedence proven on conflicting fixtures | PASS | ADV-001, ADV-002, ADV-009 and specification precedence order |
| Evidence-backed currentness and expiry | PASS | POS-002, ADV-005, ADV-013, ADV-014 |
| Vendor, protocol, framework, service, agent, and database neutrality | PASS | Gate 3 neutrality review and two independent examples |
| Explicit accountable acceptance | PASS | User instruction to continue with Step 4 on 2026-08-25 |

The specification is accepted as schema authority. Schema conformance does not
authorize a resolver, evaluator, planner, provider, runtime, consumer
migration, or implementation extraction.

## Non-goals

This specification does not:

- modify or rename frozen contracts;
- implement a resolver, evaluator, registry, planner, or runtime;
- require runtime discovery;
- create a Resource Capability;
- make planning, workflow, tool, agent, RAG, memory, model, or MCP
  constitutional;
- select providers or implementations; or
- modify a consumer repository.
