---
name: openspec-journal
description: >-
  Owns the append-only interaction journal for an OpenSpec change —
  `openspec/changes/<change>/journal.jsonl` — and the fixed event vocabulary
  written to it (change.created, artifact.added/revised, mode.chosen,
  task.start/complete/blocked, verifier.result, decision, handoff, archive,
  skill.invoked, agent.spawned, context.compacted, turn.start/end). Invoked by
  name from the openspec-* skills whenever one of those events happens; not a
  user-facing entry point on its own. Use for "log this to the journal",
  "emit a journal event", "what fields does task.complete need", or "why did
  the journal helper reject my write".
compatibility: "Python 3.9+ on PATH. No network access. Self-contained; discovers the OpenSpec workspace root by walking up for an openspec/changes/ directory."
---

# OpenSpec journal

Write one line of structured, append-only history per load-bearing interaction
inside an OpenSpec change, so a change's `journal.jsonl` becomes a session log
that survives context compaction and long-running work — not a full
transcript, and not optional narration.

## Route

Run the bundled helper that ships with this skill. Resolve
`scripts/openspec-journal.py` next to this skill's `SKILL.md` (the host skill
install path). Do **not** look for it under the product repo's `scripts/` —
that path is never installed. Keep the product repo as the working directory
so the helper can find `openspec/changes/`:

```bash
python3 <skill-dir>/scripts/openspec-journal.py <change> <event> [k=v ...]
python3 <skill-dir>/scripts/openspec-journal.py <change> show [--limit N]
python3 <skill-dir>/scripts/openspec-journal.py <change> doctor
python3 <skill-dir>/scripts/openspec-journal.py --schema
```

Run with no arguments for the full usage contract, and `--schema` for the
authoritative event-name -> required-field table. Read those outputs instead
of memorizing the vocabulary — the script is the single source of truth for
it, so a caller who invents its own field name or event name gets a rejection,
not a silent write.

## Turn bookending is the default discipline

Whenever the active working directory is inside an OpenSpec change, bookend
every user turn with two writes, independent of whether any file changed:

1. **Before starting work**, log `turn.start input="<paraphrase of the ask,
   <=200 chars>"`.
2. **After finishing**, log `turn.end output="<what changed, was decided, or
   was answered>"`.

Writing the input *before* doing the work is a commitment device against
post-hoc rationalization. This applies to every prompt, including pure Q&A
turns with no file changes.

## Ordering and length

Events describe things that already happened — log `change.created` after
`openspec new change <name>` succeeds, not before. `input`/`output` are
rejected (exit 2) above 200 characters so the caller rewrites shorter rather
than truncating silently; move long content into `design.md` or an ADR and
point at it (`output="See design.md §3 for full rationale."`).

`--input-file` / `--output-file` paths must resolve under the change
directory. Change names `.` and `archive` are rejected. Reserved fields
`ts`, `event`, and `phase` cannot be forged via `k=v`.

## Precompact hook

`scripts/openspec-journal-precompact-hook.sh` emits `context.compacted` for
the most recently active change when an agent host fires a pre-compaction
lifecycle hook (for example Claude Code's `PreCompact`). It is self-contained,
silent on any failure, and never blocks compaction. Wire it once per host;
skills never call it directly.

## Completion

Complete when the event was accepted (exit 0) and, for `show`/`doctor`, the
requested output was returned. A rejected write (exit 1 usage error, exit 2
validation error) is not silently swallowed — surface the helper's exact error
to the caller so it can fix the event name, field, or length and retry.
