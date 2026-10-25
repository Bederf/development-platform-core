# Platform-owned agent skills

These are reusable client-facing skill sources maintained by Development
Platform Core. They are packaged separately from the provider-neutral
capability definitions in `capabilities/`.

| Skill | Capability | Purpose |
|---|---|---|
| [`governed-engineering-loop`](governed-engineering-loop/SKILL.md) | Governed Engineering Loop | Harness-neutral context, authorization, execution, owner-decision, and verification semantics |
| [`serena`](serena/SKILL.md) | `symbol-aware-code-navigation` | Symbol-level code navigation and refactoring support |
| [`context7`](context7/SKILL.md) | `current-library-documentation` | Current external library documentation lookup |
| [`chrome-devtools`](chrome-devtools/SKILL.md) | `browser-runtime-inspection` | Bounded browser diagnostics and UI verification |
| [`obsidian-markdown`](obsidian-markdown/SKILL.md) | Obsidian Markdown | Vault notes with properties, links, embeds, and callouts |
| [`obsidian-cli`](obsidian-cli/SKILL.md) | Obsidian CLI | Vault search and note operations when Obsidian is open |
| [`json-canvas`](json-canvas/SKILL.md) | JSON Canvas | Obsidian canvas nodes, edges, and connections |
| [`obsidian-bases`](obsidian-bases/SKILL.md) | Obsidian Bases | Presentation views over governed vault notes |
| [`defuddle`](defuddle/SKILL.md) | Defuddle | Clean Markdown extraction from ordinary web pages |
| [`spec-to-code-compliance`](spec-to-code-compliance/SKILL.md) | Contract compliance | Compare specifications with implementation evidence |
| [`property-based-testing`](property-based-testing/SKILL.md) | Property verification | Test invariants with generated inputs |
| [`differential-review`](differential-review/SKILL.md) | Change review | Review diffs for regressions and security impact |
| [`audit-context-building`](audit-context-building/SKILL.md) | Audit context | Reconstruct architecture and data flows before analysis |
| [`supply-chain-risk-auditor`](supply-chain-risk-auditor/SKILL.md) | Supply-chain risk | Assess dependency and toolchain risk |
| [`opencode-review`](opencode-review/SKILL.md) | OpenCode Review | Run the repository-owned agent review provider |
| [`ponytail`](ponytail/SKILL.md) | Minimal implementation | Reduce over-engineering without dropping safety or quality |
| [`headroom`](headroom/SKILL.md) | Context optimization assessment | Evaluate Headroom compression and retrieval while preserving source and authority boundaries |
| [`diary`](diary/SKILL.md) | Session close-out | Record a user-requested development session in the active project's own vault |
| [`reflect`](reflect/SKILL.md) | Session reflection | Analyze project-local session records and propose evidence-backed workflow improvements |

Installation, MCP registration, and activation remain explicit consumer or
operator actions. These sources do not silently change client configuration.
