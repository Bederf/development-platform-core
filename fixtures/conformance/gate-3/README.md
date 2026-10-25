# Gate 3 Pre-Schema Conformance Fixtures

**Status:** Architecture-assurance fixtures

**Version:** 1.0.0

**Date:** 2026-08-25

These fixtures define semantic scenarios before JSON Schema, validators,
resolvers, conformance engines, or bindings are implemented.

They are deliberately implementation-neutral. Names beginning with `fixture.`
identify fake subjects and do not select a provider, runtime, protocol,
database, framework, or consumer.

## Fixture-only format

`pre-schema-semantic-fixture.v1` is a fixture-corpus label, not a platform
contract. Its keys make expected semantics reviewable:

| Key | Meaning |
|---|---|
| `fixture_id` | Stable scenario identity within this corpus |
| `category` | Positive, negative, adversarial, or regression |
| `title` | Human-readable scenario name |
| `given` | Governed inputs or deliberately invalid inputs |
| `when` | Semantic operation or attempted transformation |
| `expected` | Required verdict, outcome, and reason codes |
| `covers` | PSM operations, constitutional invariants, relationships, and conformance dimensions exercised |

The format SHALL NOT be used as a production payload or inferred to be the
future contract schema. Gate 4 derives schemas only after the candidate
specification is reconciled at field level and these fixture semantics are
accepted.

## Files

- `positive.yaml` — conformant declarations, composition, bindings, execution,
  and lineage;
- `negative.yaml` — direct violations and multidimensional conformance
  failures;
- `adversarial.yaml` — cycles, conflicts, forgery, expiry, incompatibility,
  self-certification, and authority attacks; and
- `regression.yaml` — permanent non-implication, history, compatibility, and
  neutrality protections.

## Expected verdicts

| Category | Allowed expected verdicts |
|---|---|
| Positive | `PASS` |
| Negative | `FAIL` |
| Adversarial | `REJECT`, `DENY`, `UNRESOLVED`, `REVIEW_REQUIRED`, `CONDITIONAL`, `EXPIRED` |
| Regression | `PASS` when the protected behavior is preserved |

An expected `PASS` is a fixture expectation, not an authorization decision.
