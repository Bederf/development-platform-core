---
title: Project Definition Contract v1
type: contract
status: promoted
schema: project-definition.v1
---

# Project Definition Contract v1

## Authority

`project-definition.v1` is the canonical, machine-readable project definition. It establishes project identity, intent, boundaries, architecture, security principles, lifecycle stages and success criteria before phase admission.

The JSON document is the single editable authority. Markdown is a derived or independently rendered explanation and must not be treated as an approval source.

## Governance relationship

The definition references, rather than duplicates, `project-governance.v1` through `governance_ref`. The referenced governance record remains authoritative for ownership, authority assignments, review requirements and approval policy.

The definition digest is a SHA-256 digest of RFC 8785 JSON Canonicalization
Scheme (JCS) output with the top-level `digest` field omitted. The governance
reference includes a stable locator; consumers resolve that locator first and
then verify the referenced record's exact digest. Any amendment creates a new
definition version and digest; it does not mutate an approved definition in
place.

## Lifecycle

The intended lifecycle is:

1. `proposed`: definition is being prepared and is not admitted.
2. `approved`: exact definition and referenced governance context are approved and may bind subsequent phase admission.
3. `superseded`: replaced by a later approved definition.
4. `revoked`: withdrawn under the governing approval policy.

Phase specifications inherit applicable project constraints and may narrow scope, but may not silently weaken project boundaries, security constraints or authority controls.

## Deliberate limits

This contract does not define provider selection, agent execution, worktrees, terminals, remote transport, batching or consumer-specific fields. Those belong to separate contracts and must not be smuggled into the project-definition schema.
