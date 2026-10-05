# ✨ Noticed (required)

**Every** refinement prep run includes this step after `prepare_refinement.py`.
The script is zero-token; this is the only model reasoning in the skill.

## Input

Read `facts/refinement-latest.json` produced by `./scripts/prepare-install-refinement`
(repo root).

Do **not** re-fetch Jira issues or re-run hygiene rules. Field-level gaps are
owned by `rhdh-jira-lint` long term; this step only interprets **relationships**
between signals already in `facts` (including `overlaps`).

## Task

Answer: *Given these signals and the release timeline, what 1–3 things stand out
that are not obvious from reading each signal row alone?*

Examples of valid observations:

- One issue appears in multiple signal buckets (concentration of risk).
- Most hygiene noise is low-impact except issues that also fail readiness checks.
- An Epic drives both ownership and breakdown signals near code freeze.

## Rules

- **No decisions** — never say defer, drop, or prioritize; only "stands out because …"
- **No restatement** — do not repeat counts the deterministic section already shows.
- **No filler** — if nothing non-obvious applies, do not emit `## ✨ Noticed` at all
  (you still must run this step and conclude there is nothing to add).
- When insight exists, output only:

```markdown
## ✨ Noticed

**…** (1–3 short paragraphs or bullets, issue keys as links when helpful)
```

Insert that block **after** the header (through 🔥 if present) and **before** the
first signal section from the script.
