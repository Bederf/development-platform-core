---
name: opencode-review
description: Run the platform's OpenCode Review provider for an agent-facing review of changed code when the user requests or the review gate requires it.
---

# OpenCode Review

Use the repository-owned `bin/open-code-review` wrapper when an OpenCode review
is requested. Pass only the intended revision or review-scope flags, preserve
the JSON output for evidence, and summarize findings without treating the
provider as the final authority. Combine provider output with deterministic
tests and project review rules. Do not send unrelated files or secrets to an
external provider.

The wrapper invokes the pinned local package under `tools/open-code-review/`;
do not replace it with a marketplace installation implicitly.
