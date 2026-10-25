# Core capability catalog

This directory contains versioned capability definitions. A definition states
the responsibility boundary and conformance expectations; it does not grant a
project authority or activate an implementation.

Core baseline capabilities:

- [`security-audit.v1.0.0.json`](security-audit.v1.0.0.json) — build/release
  source-only security-audit evidence validation. Radix includes this baseline
  in every new project manifest; it never runs from pre-commit or grants
  production authority.

Optional capabilities:

- [`governed-engineering-loop.v1.0.0.json`](governed-engineering-loop.v1.0.0.json) — provider-neutral bounded engineering workflow; harness adapters project its semantics.

- [`gsd-master.v3.3.4.json`](gsd-master.v3.3.4.json) — current promoted,
  governed multi-phase engineering workflow backed by the external
  `gsd:master` skill. The immutable [`gsd-master.v3.3.0.json`](gsd-master.v3.3.0.json)
  remains the rollback predecessor.
- [`ocr.v1.0.0.json`](ocr.v1.0.0.json) — deterministic and optional AI code
  review gate.
- [`backpass.v1.0.0.json`](backpass.v1.0.0.json) — evidence-backed agent
  instruction learning; central ingestion is not yet qualified.
- [`property-testing.v1.0.0.json`](property-testing.v1.0.0.json) — project-owned
  property verification boundary.
- [`symbol-aware-code-navigation.v1.0.0.json`](symbol-aware-code-navigation.v1.0.0.json) — language-aware symbol navigation and refactoring support.
- [`current-library-documentation.v1.0.0.json`](current-library-documentation.v1.0.0.json) — current external library documentation lookup.
- [`browser-runtime-inspection.v1.0.0.json`](browser-runtime-inspection.v1.0.0.json) — bounded browser inspection and UI verification.
Profiles are stored under [`profiles/`](profiles/). A profile is a versioned
specialization of a base capability; it is selectable only through the
project's capability manifest and never activates an implementation.

Projects select capabilities through the versioned
`development-capability-selection.v1` manifest. Radix resolves the manifest
but does not activate capabilities or replace project authority.
