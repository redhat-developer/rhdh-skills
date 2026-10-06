# ✨ Noticed (optional agent pass)

The script emits **✨ Noticed** from cross-signal rules (`scripts/_noticed.py`).
Use this reference only when an agent should **extend** that block — not on every
run.

## Input

Read `facts/refinement-latest.json` from the latest
`./scripts/prepare-install-refinement` run. Do **not** re-fetch Jira or re-run
hygiene rules.

## Task

Add 1–3 observations that are **not** already in the script’s Noticed section:
relationships between signals in `facts` (including `overlaps`) and the release
timeline.

## Rules

- **No decisions** — only "stands out because …"
- **No restatement** of counts or bullets already in stdout
- If nothing to add, leave the script output unchanged
