# Contract index

The Core is contract-first: schemas describe stable boundaries, while
implementations and providers remain replaceable. Payloads carry explicit
versions, evidence is referenced rather than embedded as authority, and a
provider cannot silently convert a proposal into an approved action.

## Core surfaces

| Surface | Schema or specification |
| --- | --- |
| Capability definition and selection | [`capability-definition.v1`](capability-definition.v1.schema.json), [`capability-selection.v1`](capability-selection.v1.schema.json) |
| Project definition and onboarding | [`project-definition.v1`](project-definition.v1.schema.json), [`project-governance.v1`](project-governance.v1.schema.json) |
| Requirement resolution and binding | [`REQUIREMENT-RESOLUTION-AND-BINDING-PROFILE-v1`](../docs/specifications/REQUIREMENT-RESOLUTION-AND-BINDING-PROFILE-v1.md), [`policy-decision.v1`](policy-decision.v1.schema.json) |
| Evidence and verification | [`evidence.v1`](evidence.v1.schema.json), [`evidence-binding.v1`](evidence-binding.v1.schema.json), [`verification-result.v1`](verification-result.v1.schema.json) |
| Development workflow | [`development-workflow.v1`](development-workflow.v1.schema.json), [`DEVELOPMENT-WORKFLOW-CONTRACT-v1`](../docs/specifications/DEVELOPMENT-WORKFLOW-CONTRACT-v1.md) |
| Phase specification | [`phase-specification.v1`](phase-specification.v1.schema.json), [`phase-specification-v1`](../docs/specifications/phase-specification-v1.md) |
| Review lifecycle | [`review-cycle.v1`](review-cycle.v1.schema.json), [`REVIEW-CYCLE-v1`](../docs/specifications/REVIEW-CYCLE-v1.md) |
| Agent boundary | [`agent-operating-contract.v1`](agent-operating-contract.v1.schema.json), [`agent-adapter.v1`](agent-adapter.v1.schema.json), [`agent-startup-context.v1`](agent-startup-context.v1.schema.json) |
| Radix bootstrap | [`radix-guided-bootstrap-plan.v2`](radix-guided-bootstrap-plan.v2.schema.json), [`RADIX-AGENT-PIPELINE-CONTRACT-v1`](../docs/specifications/RADIX-AGENT-PIPELINE-CONTRACT-v1.md) |
| Architecture evidence | [`architecture-graph.v1`](architecture-graph.v1.schema.json), [`architecture-delta.v1`](architecture-delta.v1.schema.json) |

## Contract rules

- Every payload declares its contract version.
- Consumers may reject unsupported major versions.
- Providers return typed status and evidence; they do not fabricate authority.
- Credentials are represented only by opaque references.
- Selection and conformance do not authorize activation or execution.
- A binding requires an explicit policy decision.
- Examples and fixtures are synthetic and do not represent production data.

The [constitution](../docs/constitution/PLATFORM-CONSTITUTION-v1.md) explains
the invariants behind these rules; the [GSD Master integration note](../docs/integrations/gsd-master.md)
explains how lifecycle orchestration consumes them.
