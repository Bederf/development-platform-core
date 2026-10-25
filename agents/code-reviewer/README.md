# Development Platform Code Reviewer

Versioned, provider-neutral scaffold for an independent GSD implementation
reviewer.

The agent is deliberately narrow: it reads a specification, diff, tests,
architecture constraints, and returned evidence, then produces structured
findings. It never edits the repository or grants completion authority.

The registration proposal is inactive until a runtime adapter, tool-broker
enforcement, fake-provider conformance, and explicit project approval exist.

The Core in-process bridge is available as
`adapters.independent_review.IndependentReviewAdapter`. It requires separate
implementation and reviewer context identifiers, validates the request and
provider result, and produces a bounded review-cycle record. External process
transport, credential injection, and project registration remain runtime gates.

Gemini `gemini-3.1-flash-lite` is the first live provider to pass the bounded
qualification benchmark. It is eligible for the provider-neutral adapter, but
this record does not activate runtime execution or grant completion authority.
