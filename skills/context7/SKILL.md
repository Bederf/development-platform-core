---
name: context7
description: Use Context7 MCP to retrieve current, library-specific documentation when implementation depends on external framework or package APIs.
---

# Context7 documentation lookup

Use Context7 when a task depends on the current API, configuration, or usage
of an external library or framework.

- Resolve the exact library and version when possible before retrieving docs.
- Prefer Context7 documentation over memory for version-sensitive API details.
- Treat retrieved documentation as technical reference, not project authority;
  reconcile it with the repository's lockfiles, tests, and local conventions.
- If Context7 is unavailable, say so and use local documentation or another
  authoritative source. Do not invent API details.
- Do not use this skill for generic explanations that do not depend on a
  specific external library.

This skill adapts the versioned `current-library-documentation` capability.
