---
name: headroom
description: Evaluate or configure Headroom context compression for AI agents while preserving source bytes, provenance, authority, and explicit control over runtime changes.
---

# Headroom — Context Compression Evaluation

Use when the user asks to evaluate, install, configure, or troubleshoot
Headroom (`headroomlabs-ai/headroom`) as a context-compression layer. The
skill provides a decision and qualification workflow; its presence does not
install or activate Headroom.

## Authority and activation

- Read the active project's instructions and current Headroom qualification
  decision before proposing runtime use. Core currently retains Headroom as
  reference-only and unqualified; that status cannot be changed by this skill.
- Do not install packages, deploy services, start a proxy, wrap an agent,
  register an MCP server, route provider traffic, or change client/user-level
  configuration unless the user explicitly requests that exact action and
  its target.
- `headroom wrap` may start a proxy and alter agent configuration; treat it as
  persistent configuration. Explain the target and reversibility before
  applying it, and use `headroom unwrap <tool>` only when the user requests
  removal.
- Do not use real provider credentials or send provider traffic to force a
  positive qualification result. Prefer seeded, offline fixtures and a local
  fake upstream.
- The supplied project description says telemetry is enabled by default and
  that `headroom learn --apply` can edit instruction files. Surface those
  effects before activation; never run `headroom learn --apply` without the
  user's explicit approval of the exact files to change. A local compression
  path does not by itself establish that all telemetry or memory is local.

## Evaluation workflow

1. Identify the exact version, operating mode (library, proxy, agent wrap, or
   MCP), enabled features, storage/retention behavior, and whether network or
   telemetry paths are active. Separate user-provided product claims from
   behavior verified in the target environment.
2. Compare the current context projection and Headroom on the same bounded
   fixture. Keep the original source available and associate each optimized
   projection with a retrieval reference.
3. Measure original and projected token estimates, relevant content retained
   inline, deferred/truncated content, retrieval success, source/projection
   digests, authority/trust preservation, processing time, and cost when
   available.
4. Verify retrieval returns the exact original bytes identified by the
   reference. Test missing CCR activation, unavailable retrieval, adversarial
   content (including spoofed system/authority markers), and task correctness.
   A smaller prompt or retained keyword alone is not a pass.
5. Report each tested route and result separately. Fail qualification if the
   original cannot be recovered exactly, its digest or authority changes, the
   optimizer introduces sources, or failure silently degrades to unverified
   compressed context.

## Outcome

Return the tested version and mode, environment and traffic boundary, fixture
and measurements, exact retrieval and task-correctness results, unresolved
risks, and a clear disposition. Keep a useful compression ratio separate from
qualification. Do not claim Core contract, dependency, proxy, MCP, or context
authority approval unless a governed decision explicitly grants it.
