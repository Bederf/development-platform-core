# Development Platform Core

An open engineering foundation for building software with explicit contracts,
bounded automation, evidence-backed verification, and replaceable adapters.

This is the public, source-first showcase of my development-platform work. It
focuses on the parts that are useful to study and reuse:

- versioned contracts and JSON Schemas;
- capability discovery, requirement resolution, and governed binding;
- Radix project bootstrap and workspace orchestration;
- adapter boundaries for review, evidence, providers, and execution;
- deterministic fixtures, examples, and conformance tests.

The central design idea is simple: an agent or provider may propose work, but
contracts, policy, evidence, and explicit acceptance boundaries determine what
can proceed. Core is vendor-neutral and does not prescribe a model provider,
application architecture, deployment platform, or agent runtime.

## Relationship to GSD Master

[GSD Master](https://github.com/Bederf/gsd-master) is the companion lifecycle
orchestration skill. Core owns contracts, authority boundaries, evidence, and
conformance surfaces; GSD Master owns phase planning, execution waves, review
routing, bounded correction, and closeout. They are separate projects with
separate release identities and are intentionally linked rather than
duplicated.

See [the integration boundary](docs/integrations/gsd-master.md).

## Public-release boundary

This repository is a portfolio-quality public slice. Private vault notes,
consumer evidence, review payloads, credentials, runtime state, deployment
details, and historical custody records are excluded. Product-specific code is
also kept outside this repository.

The current implementation maturity is mixed by design: contracts and
conformance fixtures are the strongest surface; adapters and orchestration
paths are reference implementations and integration boundaries, not a hosted
platform or a universal autonomous-agent runtime.

## Explore

- [Platform constitution](docs/constitution/PLATFORM-CONSTITUTION-v1.md)
- [Platform contract model](docs/constitution/PLATFORM-CONTRACT-MODEL-v1.md)
- [Platform semantic model](docs/constitution/PLATFORM-SEMANTIC-MODEL-v1.md)
- [Capability model](docs/specifications/CAPABILITY-DEFINITION-SPECIFICATION-v1.md)
- [Contract index](contracts/README.md)
- [Radix adapters](adapters/radix/)
- [Conformance fixtures](fixtures/conformance/)
- [Examples](examples/)

## Run the public checks

```bash
python -m pip install -e '.[dev]'
pytest -q
```

The schemas and fixtures are self-contained and do not require external
services or secrets.

## Project status

**Maturity: public source-first foundation / active reference implementation.**
Contracts, schemas, fixtures and conformance surfaces are the most complete
parts of this release. Adapters are intentionally replaceable examples; this
repository is not a hosted platform or a turnkey autonomous-agent runtime.

## Fastest tour

```bash
python -m pip install -e '.[dev]'
pytest -q
```

Start with the [contract index](contracts/README.md), then follow the
[GSD integration boundary](docs/integrations/gsd-master.md).

## License

Copyright (c) Pieter van Rooyen. Released under the MIT License; see
[`LICENSE`](LICENSE). Third-party material remains subject to its own notices.
