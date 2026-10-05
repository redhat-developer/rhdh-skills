# Prepare RHDH Install refinement briefing

Ceremony-specific, signal-driven briefing for the Install team. **Two steps:**
one script run, then required **✨ Noticed** interpretation.

## 1. One command

Repo root:

```bash
./scripts/prepare-install-refinement
```

This skill directory:

```bash
./prepare-refinement
```

Fixture / CI (no Jira):

```bash
./scripts/prepare-install-refinement \
  --fixture skills/jira/rhdh-install-prepare-refinement/fixtures/refinement-queue.sample.json \
  --today 2026-10-05
```

Stdout is the briefing markdown. Facts for Noticed are written automatically to
`skills/jira/rhdh-install-prepare-refinement/facts/refinement-latest.json`
(stderr logs the path).

Auth for live Jira: `JIRA_EMAIL` + `JIRA_API_TOKEN`, or `.jira-token` next to `acli`.

Unit tests (repo root):

```bash
uv run pytest tests/unit/test_install_prepare_refinement.py -q
```

Do not deliver script stdout alone — continue to step 2.

## 2. ✨ Noticed (required)

Load `references/noticed.md`. Read `facts/refinement-latest.json`. Produce
`## ✨ Noticed` and insert it after the header block (through 🔥 if present),
before the first signal section.

Omit the `## ✨ Noticed` heading only when no non-obvious cross-signal insight
exists. The skill is **not complete** until this step runs.

## Boundaries

- **Does not** reimplement `rhdh-jira-lint` field enforcement.
- **Does not** replace `/rhdh-jira-refine` per-issue exit-criteria audits.
- **Does not** write Jira — read-only briefing.

## Configuration

- `references/config.json` — team id, queue scope, dashboard URLs.
- `assets/release_calendar.json` — code freeze dates (align with jira-lint).
