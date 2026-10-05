# Prepare RHDH Install refinement briefing

Ceremony-specific, signal-driven briefing for the Install team. Deterministic
scripts assemble facts and markdown; an optional **✨ Noticed** pass adds
cross-signal interpretation only when useful.

## Run (zero-token)

From this skill directory:

```bash
cd skills/jira/rhdh-install-prepare-refinement
uv run python scripts/prepare_refinement.py
```

Offline / CI:

```bash
uv run python scripts/prepare_refinement.py \
  --fixture fixtures/refinement-queue.sample.json \
  --today 2026-10-05
```

Facts for the optional LLM layer:

```bash
uv run python scripts/prepare_refinement.py --fixture fixtures/refinement-queue.sample.json \
  --today 2026-10-05 --facts-out /tmp/refinement-facts.json
```

Auth: `JIRA_EMAIL` + `JIRA_API_TOKEN`, or `.jira-token` next to `acli` (same as
other RHDH skills).

## Optional ✨ Noticed

After the script prints markdown, load `references/noticed.md` and run **one**
reasoning pass on the facts JSON. Omit the section if nothing non-obvious applies.

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
