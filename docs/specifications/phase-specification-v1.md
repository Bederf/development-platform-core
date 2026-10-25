# phase-specification.v1 implementation

The canonical schema is `contracts/phase-specification.v1.schema.json`.
Validation and resolution are provided by
`adapters/phase_specification.py`.

The validator enforces schema shape, unique requirement/criterion/task
identities, requirement and dependency references, acyclic task dependencies,
the derived-only workflow identity rule, and the content hash. It does not
convert runtime evidence into semantic requirements.

`inspect_historical_phase()` is intentionally a compatibility inspection tool,
not a migration writer. It reports recoverable Markdown facts and an explicit
migration gap. Historical phases must be reviewed before a canonical
specification is authored.

This implementation does not modify or integrate `gsd-master/SKILL.md`.
