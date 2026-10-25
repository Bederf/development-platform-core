---
name: serena
description: Use symbol-aware repository navigation and refactoring when a Serena MCP server is available; applies to cross-file code understanding, impact analysis, and safe renames.
---

# Serena symbol-aware development

Use symbol-level navigation for definitions, references, imports,
implementations, and call sites before cross-file code changes.

- Check that Serena MCP is exposed by the current client; never claim it was
  used when it was unavailable.
- Use ordinary search for prose, configuration, exact strings, and files outside
  the language-server scope.
- Before broad refactors, inspect the definition and references, then verify
  the affected symbols and run project checks afterward.
- Serena reports relationships; it does not authorize changes, replace tests,
  or silently install or change tooling.
- If unavailable, state the limitation and use the best available fallback.

## Explicit setup

Only when the user explicitly requests installation or configuration, use the
documented Serena setup for the target client. On Linux/macOS, the managed
installation shape is:

```bash
uv tool install -p 3.13 serena-agent
serena init
```

Then register the server with the selected client and restart that client.
For clients supported by Serena's setup helper, prefer:

```bash
serena setup codex
serena setup claude-code
```

The Codex registration uses `serena start-mcp-server --context=codex
--project-from-cwd`, which scopes project activation to the working directory.
Use an absolute executable path when the client's environment cannot resolve
`serena` or `uv`. Confirm the target project path before activation. Existing
client configurations may use an equivalent `uvx` or `npx` transport; do not
replace one automatically.

This skill adapts the versioned `symbol-aware-code-navigation` capability.
