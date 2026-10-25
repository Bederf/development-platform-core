# phase-specification.v1 compatibility validation

**Date:** 2026-09-22
**Mode:** read-only compatibility inspection

## Phase 302C

Recoverable facts include the phase identifier (`302C`), version (`2.1.1`),
title, scope constraints, authorization status, review references, and
acceptance-criteria text. The historical file does not provide a complete
canonical requirement/evidence/task contract or immutable specification hash.
It is therefore **representable only after an explicit migration review**.
No missing requirements or evidence contracts are inferred.

## Phase 310-06F

The file contains strong semantic prose covering evidence sufficiency,
provenance, refusal behavior, confidence, response shape, and governance
boundaries. It does not expose a parseable phase identity/version pair or a
complete stable requirement/task/evidence contract. It is **semantically
representable, but not automatically migratable** without an explicit owner
decision converting the normative sections into canonical requirement records.

## Golden run

The golden run contains the derived fields needed by acceptance:

- specification reference;
- requirement evaluations;
- implementation revision;
- verification evidence;
- independent review and review cycle;
- convergence result; and
- workflow/acceptance identity.

The original `specification.md` is only a small Markdown record, so the fixture
assembled semantic facts from several JSON artifacts. Under
`phase-specification.v1`, those semantic facts must originate in one canonical
specification. The existing fixture is therefore a **downstream compatibility
reference**, not a canonical phase-specification.v1 document.

## Compatibility conclusion

All three cases can be inspected without mutating historical state. None can
be silently upgraded by the validator. A future migration adapter may create a
new approved specification only after the missing semantic decisions are
explicitly supplied and reviewed.
