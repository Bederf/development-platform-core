---
name: reflect
description: Analyze project-local session records for recurring, evidence-backed workflow lessons and present governed proposals for improvement.
---

# Reflect — Project-Scoped Session Learning

Use when the user asks to reflect on diary/session notes or invokes this skill.
Reflection analyzes evidence and proposes changes; it does not silently edit
instructions, skills, policies, memory, or other governed sources.

## Scope

- Default to the active Git repository and its own session records, as
  determined by repository instructions and established note conventions.
- Analyze multiple projects only when the user explicitly asks for a
  cross-project reflection.
- Honor requested date ranges, entry counts, project filters, and topic
  filters. State the selected scope and filters before reporting findings.
- If the user gives no date range or entry count, analyze the ten newest
  project-local session records by their recorded date. Do not skip records
  based on an assumed processed-entry log; honor one only if project
  instructions define it.
- Sort newest first; break equal-date ties by filename in descending
  lexicographic order. Exclude records with missing or invalid dates from this
  default selection and report how many were excluded. If the user specifies
  a date range, report undated or malformed records that could not be
  evaluated against it.
- Do not assume a global diary directory, reflection log, memory location, or
  filename pattern. Discover them from the active project's instructions and
  existing notes.
- If no applicable records can be identified, explain what was checked and
  ask for the missing scope or source.

## Analysis

1. Read each selected record in full and distinguish recorded facts from
   inference.
2. Group observations into recurring patterns, conflicting signals, and
   one-off events. Require at least two independent occurrences before
   calling something a pattern; label confidence and evidence count.
3. Separate project-specific practices from cross-project preferences. Call a
   lesson cross-project only when evidence appears in at least two distinct
   projects. Do not generalize a project convention from repeated sessions in
   one repository into a global rule.
4. Check proposed lessons against the project's authoritative instructions
   and existing decisions. Surface conflicts instead of resolving them by
   editing the source. Resolve scope/version and superseding owner decisions
   before treating an old failure, promotion claim or waiting condition as
   current. Distinguish standing controls, blocked prerequisites and deliberate
   deferrals from actionable work; date and checkbox order are not authority.
5. Recommend concise, actionable changes with source-note references and
   explain expected benefit and risk.
6. When a recurring, evidence-backed finding concerns the behavior of GSD
   Master, check whether the active project has relevant GSD run audits and
   transcripts in the location defined by the GSD skill. Run its
   improvement-candidate analysis only when that audit evidence exists:

   ```text
   gsd:master improvement-candidate:{concise issue and supporting run/session evidence}
   ```

   Pass the concise issue and diary references as context, while letting GSD
   analyze its own run-audit evidence. If diary evidence suggests a GSD issue
   but no relevant audit or transcript is available, report the missing
   evidence and retain the issue as a proposed follow-up; do not present a
   diary-only observation as a completed GSD skill audit. Cite GSD run/audit
   identifiers in the reflection when available; do not invent or create
   missing evidence. Do not invoke this for unrelated workflow findings, and
   do not treat the GSD report as approval to edit or adopt a change. If the
   GSD Master skill is unavailable, report that limitation and retain the
   evidence-backed recommendation in the reflection.

## Output and governance

Return the scope and filters, records examined, and any records excluded with
the reason. For each pattern, state its evidence count, confidence, and the
specific source-note paths; include relevant counterexamples or contradictory
evidence. Separate patterns, one-off observations, and proposed follow-up
actions. Include suggested text or a diff when useful. Keep recommendations
separate from approved policy.

When project instructions require a qualification/source handoff, distinguish
session closure, tested scope, live-provider verification, consumer adoption
and implementation revision. Identify diary-only commits and uncommitted
implementation separately. Respect accepted noncommitted-evidence exceptions;
do not infer lost work from a dirty checkout. Repeated notes about one ongoing
condition are not independent technical incidents.

For a dated follow-up lacking a completion record, report "not confirmed in the
selected evidence" rather than declaring operational failure. Recommend a
bounded check of the authoritative record; do not execute destructive cleanup
or reopen deferred work merely because an old deadline has passed.

Do not modify `AGENTS.md`, `CLAUDE.md`, skills, contracts, project memory, or
other instruction sources as a side effect. Do not mark proposals as adopted
or update processed-entry state unless the user explicitly requested that
specific write and the project instructions permit it. A user request to
reflect authorizes analysis and reporting, not automatic promotion of
recommendations.

## Privacy

Use only the selected project records. Do not copy transcripts, credentials,
raw tool output, or unrelated project data into a reflection. Keep references
to source records sufficient for a human to verify each finding.
