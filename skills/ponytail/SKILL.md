---
name: ponytail
description: Reduce unnecessary implementation while preserving correctness, security, validation, accessibility, and error handling.
---

# Ponytail minimal implementation

Use this skill during coding tasks when the solution may be over-engineered.
Understand the touched code and real requirements first, then choose the first
option that satisfies them:

1. Does this need to exist?
2. Can existing project code be reused?
3. Can the standard library handle it?
4. Is there a native platform feature?
5. Is an installed dependency already suitable?
6. Can the requirement be met simply?
7. Otherwise, write the minimum complete implementation.

The ladder applies to implementation, not investigation. Never remove or skip
trust-boundary validation, authorization, error handling, data-loss safeguards,
tests, accessibility, or required observability merely to reduce line count.
Do not add dependencies, abstractions, wrappers, configuration, or speculative
features without a demonstrated requirement. Verify the resulting behavior
with the project's relevant checks.

Ponytail is an optional style guide. It does not override platform contracts,
project specifications, security policy, or user requirements.
