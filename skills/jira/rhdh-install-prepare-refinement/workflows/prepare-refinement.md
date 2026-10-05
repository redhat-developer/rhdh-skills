# Prepare RHDH Install refinement briefing

Ceremony-specific, signal-driven briefing for the Install team. **Two steps:**
deterministic script, then required **✨ Noticed** interpretation.

## 1. Run the script (zero-token)

From this skill directory:

```bash
cd skills/jira/rhdh-install-prepare-refinement
uv run python scripts/prepare_refinement.py --facts-out /tmp/refinement-facts.json
```

Offline / CI:

```bash
uv run python scripts/prepare_refinement.py \
  --fixture fixtures/refinement-queue.sample.json \
  --today 2026-10-05 \
  --facts-out /tmp/refinement-facts.json
```

Auth: `JIRA_EMAIL` + `JIRA_API_TOKEN`, or `.jira-token` next to `acli` (same as
other RHDH skills).

The script prints the signal markdown to stdout. Do not deliver that output alone.

## 2. ✨ Noticed (required)

Load `references/noticed.md`. Read `/tmp/refinement-facts.json` (or `--facts-out`
path). Produce `## ✨ Noticed` and **insert it into the briefing** after the
header block (through 🔥 if present) and **before** the first signal section
(`## 🚀`, `## 🎫`, etc.).

Omit the `## ✨ Noticed` heading only when `noticed.md` rules say there is no
non-obvious cross-signal insight — never skip this step; only skip empty output.

The skill is **not complete** until this step runs.

## Boundaries

- **Does not** reimplement `rhdh-jira-lint` field enforcement — extend via shared
  violation codes later.
- **Does not** replace `/rhdh-jira-refine` per-issue exit-criteria audits.
- **Does not** write Jira — read-only briefing.

## Configuration

- `references/config.json` — team id, queue scope, dashboard URLs.
- `assets/release_calendar.json` — code freeze dates for urgency (keep aligned with
  jira-lint calendar).

Dashboard gadget JQL should be copied into config as the spike matures; headings
link to those filters, not dashboard homepages.
