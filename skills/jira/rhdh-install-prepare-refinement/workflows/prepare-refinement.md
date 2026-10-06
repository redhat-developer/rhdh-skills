# Prepare RHDH Install refinement briefing

Ceremony-specific, signal-driven briefing for the Install team. One script run
produces the full markdown (including deterministic **✨ Noticed**).

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
  --fixture tests/fixtures/install_refinement_queue.json \
  --today 2026-10-05
```

Stdout is the full briefing: header, **✨ Noticed** (deterministic cross-signal
rules), then signal sections. Facts JSON is also written to
`skills/jira/rhdh-install-prepare-refinement/facts/refinement-latest.json`
(stderr logs the path).

Auth for live Jira: `JIRA_EMAIL` + `JIRA_API_TOKEN`, or `.jira-token` next to `acli`.

Unit tests (repo root):

```bash
uv run pytest tests/unit/test_install_prepare_refinement.py -q
```

## 2. ✨ Noticed (agent, when richer insight is needed)

The script already emits Noticed from `overlaps` and release urgency. When
invoking the **skill** in an agent, load `references/noticed.md` and optionally
replace or extend that block using the facts JSON — never re-fetch Jira.

## Boundaries

- **Does not** reimplement `rhdh-jira-lint` field enforcement.
- **Does not** replace `/rhdh-jira-refine` per-issue exit-criteria audits.
- **Does not** write Jira — read-only briefing.

## Configuration

Install team scope and release freeze dates live in `scripts/_config.py` (align
calendar with rhdh-jira-lint when dates change).
