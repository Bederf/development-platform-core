---
name: property-based-testing
description: Design property-based tests for transformations, parsers, validators, serializers, algorithms, and platform invariants.
---

# Property-based testing

Use when generated inputs can exercise an invariant more effectively than a
small set of examples. Prefer round-trip, idempotence, invariant, ordering,
oracle, and no-exception properties as appropriate. Keep generators bounded and
reproducible, preserve failing examples, and integrate with the repository's
existing test runner. Do not use it as a substitute for integration tests when
the behavior depends on external systems.
