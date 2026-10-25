---
name: diary
description: Close a user-requested development session by recording a concise, project-local diary entry that follows the active repository's instructions and note conventions.
---

# Diary — Project-Local Session Close-Out

Use only when the user explicitly asks to close out a session, requests a diary
entry, or invokes this skill. Do not create diary entries automatically after
ordinary work.

## Vault boundary

1. Resolve the active project root and read its governing `AGENTS.md` files.
2. Use the project vault and note location specified by its instructions. If
   none is specified, follow the existing project convention; do not assume a
   global vault, `MEMORY.md`, directory name, or filename convention.
3. Never write to a parent, sibling, consumer, or global vault while closing
   out another project. If the active vault cannot be identified safely, stop
   and ask the user.
4. Preserve unrelated worktree changes. Stage or commit only when requested or
   when project instructions explicitly require it; never use broad staging.

## Workflow

1. Gather the current date/timezone, project focus from authoritative project
   control notes, last commit, worktree status, and relevant documentation
   surfaces. Do not treat memory or a diary as authority over project control
   sources.
2. Inspect existing session notes and follow their format. If no convention
   exists, write a short Markdown note with date, task, work completed,
   decisions, blockers, changed files, verification, and carry-forward focus.
3. Update a project memory or latest-session pointer only if project
   instructions establish one. Preserve its format and authority boundaries;
   do not invent a new memory system.
4. Update architecture notes or diagrams only if this session changed the
   project map and its instructions require synchronization. Use the relevant
   project skill and validate edited artifacts.
5. Extract a reusable lesson only when it describes a repeatable method, and
   follow project conventions for where such lessons belong.
6. Report the note path, any synchronized surfaces, verification, commit (if
   made), and unrelated dirty changes left untouched.

## Qualification summary and source checkpoint

When project instructions require a qualification handoff (as Core does),
include this concise summary in the existing diary format:

- **Verified scope:** the exact behavior and test boundary exercised.
- **Live provider:** verified, failed, pending, or not applicable, with evidence.
- **Consumer adoption:** the exact adopted scope, pending, or not applicable.
- **Source checkpoint:** the implementation commit, or task-owned file hashes
  plus the base revision and outstanding commit work. Hashes identify source;
  they do not make an uncommitted checkout recoverable or release-ready.
- **Remaining checks:** each unresolved check and its authoritative record.

Keep links to the governing records rather than creating a second status
authority. Record accepted noncommitted-evidence exceptions explicitly. Never
fold earlier unrelated work into a commit to make the handoff appear complete.
An implementation checkpoint belongs to the development work; a diary-only
commit must be labeled as such.

Before suggesting carry-forward work, resolve the current owner decision,
scope/version and supersession. Classify the item as actionable, a standing
control, a blocked prerequisite or deliberately deferred. Preserve historical
decisions and do not equate the newest note or first unchecked item with
authorization. If the records conflict, state the uncertainty and the exact
record that needs resolution.

## Obsidian notes

For Obsidian vault notes, use `obsidian-markdown` for properties, wikilinks,
callouts, and embeds. Use `obsidian-cli` only when the desktop application is
open. Use `json-canvas` when creating or editing Canvas files and validate IDs
and edge references after each change. Do not create Bases or import web pages
during routine close-out.

## Authority and privacy

- The diary is a resume aid, not a replacement for project policy, task
  authority, or runtime state.
- Do not save transcripts, credentials, raw tool output, or unrelated product
  data.
- Do not silently resolve conflicts between notes and authoritative sources;
  report them.
- Do not edit another project's files or commit pre-existing user changes.
