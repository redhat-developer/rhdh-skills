# ✨ Noticed (optional LLM layer)

Run **after** `prepare_refinement.py` emits markdown and `--facts` JSON. The script
is zero-token; this step is the only place an model may run.

## Input

Pipe or read the compact `facts` object from:

```bash
uv run python scripts/prepare_refinement.py --facts -
```

Do **not** re-fetch Jira issues or re-run hygiene rules. Field-level gaps are
owned by `rhdh-jira-lint` long term; this skill only interprets **relationships**
between signals already in `facts`.

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
- **Omit the section entirely** if nothing non-obvious applies (no "all good" filler).
- Output only:

```markdown
## ✨ Noticed

**…** (1–3 short paragraphs or bullets, issue keys as links when helpful)
```

Place `## ✨ Noticed` **after** the header block and **before** signal sections.
