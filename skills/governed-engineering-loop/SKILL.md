---
name: governed-engineering-loop
description: Apply the platform-neutral governed engineering workflow when compiling project context, resolving plan authority, executing bounded work, and completing verification across any agent harness.
---

# Governed Engineering Loop

Use this Core capability to preserve the boundary between project context,
authority, agent execution, and independent verification.

## Required behavior

- Treat the project snapshot as derived context, never as authorization.
- Resolve authorization independently from its declared source, scope, and
  validity.
- After a bounded plan is authorized, continue implementation, tests, review,
  and commit without repeated approval prompts for ordinary in-scope work.
- Escalate only for scope expansion, destructive or external effects,
  production changes, secrets, or invalid/expired authorization.
- Preserve evidence, provenance, uncertainty, and lifecycle state.
- Leave final correctness and acceptance to independent verification.

## Owner-decision gates

Before declaring a phase blocked:

1. Search the authoritative sources for the missing decision.
2. Classify findings as `confirmed`, `incomplete`, `conflicting`, or `absent`.
3. If unresolved, use [the owner-decision request template](references/owner-decision-request.md).
4. Ask questions in plain language; do not require the owner to know the
   internal schema.
5. Clearly label recommendations as recommendations.
6. Never invent or silently approve policy.
7. Classify the owner's response as one of: `proposal`, `confirmed decision`,
   `superseding decision`, or `deferred decision`.
8. A project artifact MUST NOT silently override a canonical authority source.
   When an owner response conflicts with canonical authority, treat it as a
   `proposal` until the owner explicitly confirms that it supersedes the
   source.
9. Before recording a `superseding decision`, identify the canonical authority
   source, ask whether the owner intends to supersede it, update or reference
   the canonical source with attributable owner identity, decision date,
   version or revision identity, scope, rationale, and superseded reference,
   then reconcile the derived artifact against that source.
10. Re-run the applicable independent review after the canonical or derived
    artifact changes. Only then proceed to the owner gate or implementation.
11. Translate a plain-language answer into the governed decision record,
    preserve provenance and remaining uncertainty, and resume approved work.

## Harness boundary

This is a Core semantic skill. A harness adapter may provide its own
invocation, prompt, TUI, MCP, and lifecycle integration, but may not redefine
these rules. `gsd:master` is one possible workflow adapter; it is not the
source of this contract.

The Core capability may be projected into a harness through the versioned
`capability-projection.v1` plan. A projection plan records the Core source,
harness adapter, target, status, and activation policy. It does not install or
activate the target. The adapter must report discovery, advertisement, loading,
connection, and health as separate states.
