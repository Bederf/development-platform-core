# Owner decision required

Use this template when authoritative sources do not fully resolve a required
policy or methodology decision.

## Decision N — <plain-language title>

Evidence status: confirmed | incomplete | conflicting | absent

Owner response classification: proposal | confirmed decision | superseding decision | deferred decision

Why this matters:

<short explanation of what implementation depends on>

Evidence found:

- Source: `<path>`
- Section: `<section>`
- Status: `confirmed | incomplete | conflicting | absent`
- Summary: `<faithful summary>`

Recommended option:

<recommendation, clearly labelled as non-authoritative>

Options:

1. **Approve** — `<meaning and consequence>`
2. **Modify** — `<what must be specified>`
3. **Defer** — `<what remains blocked>`

Reply in plain language, for example:

```text
Approve 1, modify 2 to <change>, defer 3.
```

After the owner responds, record the decision with its source, source hash
when available, responder, timestamp, scope, and any remaining uncertainty.
Classify the response as a proposal, confirmed decision, superseding decision,
or deferred decision. A conflicting response is only a proposal until the
owner explicitly confirms supersession. A superseding decision must also
identify and update or reference the canonical authority source with owner
identity, decision date, version or revision identity, scope, rationale, and
the superseded reference. Reconcile the derived artifact and rerun applicable
independent review before continuing.
