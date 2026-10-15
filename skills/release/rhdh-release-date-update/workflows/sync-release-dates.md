# Sync release dates — full run

Run every command from **this skill's directory** (the folder containing
`SKILL.md`), not the rhdh-skills repository root. Every `scripts/release_dates.py`
invocation uses `uv run --script` — the script declares `ruamel.yaml` through
PEP 723, and only `uv run --script` resolves that dependency without the
repository's own dev environment, per ADR-0002's YAML exception. A bare
`scripts/release_dates.py ...` relies on the shebang, which cannot work on
Windows, where the skill also runs.

Create one working directory for the run and use its path throughout — never a
literal `/tmp` path, which does not exist on Windows:

```bash
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/rhdh-release-dates.XXXXXX")  # Windows: %TEMP% or tempfile.mkdtemp()
```

## 1. Capability gate

```bash
uv run --script scripts/release_dates.py check
```

Fails closed if `gh auth status` or `glab auth status --hostname
gitlab.cee.redhat.com` fails. Stop and tell the human to run
`/setup-rhdh-skills` (Jira/GitHub/GitLab authentication) — do not proceed on a
missing capability.

## 2. Get source-of-truth dates

Invoke `/rhdh-release-schedule` for every RHDH version **currently active**
(its `dates` path enumerates these on its own), plus any **planned** version
the human explicitly named in the request. Transcribe the answer — including
which source produced each date — into the source-JSON shape in
`references/target-schemas.md`, and write it to `$WORKDIR/source.json`.

Planned releases cannot be enumerated: `/rhdh-release-schedule`'s planned path,
`future-dates {{VERSION}}`, requires a version from the caller, and that
skill's own workflow says not to answer for every release at once. A planned
release the human never named is outside this run's scope — say so in the
final report rather than reporting a false clean, and do not guess at which
planned versions might exist.

This step is not scriptable: `/rhdh-release-schedule` itself reads Jira and a
spreadsheet through an agent, not a fixed API call. Everything after this
step is deterministic.

Four things go wrong here if you transcribe on autopilot. The field mapping is
in `references/target-schemas.md` — read it before building the JSON:

- `ga_push` is the **GA announce** date, not Go/No Go & Push.
- The planned-release path normalizes the version to `x.y` (for example
  `"2.2"`) and names the GA field `ga_date`. Restore the patch component —
  `x.y.0` — and rename `ga_date` to `ga_push` when building the source JSON.
  Passed through unchanged, the version is reported `invalid` and `ga_push` is
  reported missing.
- `backstage_version` is **not** something `/rhdh-release-schedule` reports.
  Read it from the target file's existing entry, or ask the human for a release
  being added. Omit the field rather than guessing — the script preserves what
  is already in the file and reports the omission, but a guessed value reaches
  third-party plugin owners as the Backstage version to target.
- Leave z-stream versions such as `1.10.5` out. Both files track `x.y.0` only.

## 3. Diff

```bash
uv run --script scripts/release_dates.py diff --source-json "$WORKDIR/source.json"
```

Read the JSON report. Each target (`github`, `gitlab`) lists one entry per
version with `state`:

| State | What to do |
|---|---|
| `match` | Nothing |
| `stale` | Fix it — `desired` holds the corrected fields |
| `missing` | Add it — absent from the file and fully specified |
| `incomplete` | Absent, but the source lacks `missing_fields`. Do not write a partial entry: ask the human for those values and re-run, or report it as needing a human |
| `invalid` | A supplied date is not `YYYY-MM-DD`, or the version is not `x.y.0` — `invalid_fields` or `error` names the problem. Fix the transcription and re-run; never force a value through |
| `skipped-tbd` | Feature Freeze undecided upstream — leave alone |
| `skipped-zstream` | Not an `x.y.0` release; neither file tracks it |

Every state is named in the final report, including the skipped ones.

If no entry across both targets is `stale` or `missing`, skip to step 7 and
report a clean run — still naming any `incomplete` or `invalid` entries and the
pinned-issue gap.

## 4. Render

For each target with at least one `stale` or `missing` entry:

```bash
uv run --script scripts/release_dates.py render --target github \
  --source-json "$WORKDIR/source.json" --output "$WORKDIR/rendered-github.yaml"
uv run --script scripts/release_dates.py render --target gitlab \
  --source-json "$WORKDIR/source.json" --output "$WORKDIR/rendered-gitlab.yaml"
```

`render` regenerates the whole file from source-of-truth every time — never a
partial patch — so re-running this workflow is always safe. It never touches
a version absent from the source JSON, so historical entries are untouched.

Each render's JSON output includes `source_revision` — the exact base-file
revision it read. Hold on to it per target; step 6's `apply` command needs it
to detect whether the base file moved before the push actually happens.

## 5. Get the PR / MR creation command from `/rhdh-forge`

For each target with drift, invoke `/rhdh-forge` by name to construct:

- GitHub: a `gh pr create` payload for `redhat-developer/rhdh-plugin-export-overlays`,
  base `main`, head `rhdh-release-date-update`, title `Update RHDH release
  schedule dates`, body summarizing which versions changed and why (cite
  `/rhdh-release-schedule`'s source per version).
- GitLab: the equivalent `glab`/`glab api` merge-request creation payload for
  `rhidp/rhdh-jira-lint` on `gitlab.cee.redhat.com`, same base/head/title
  convention.

`/rhdh-forge` also hands back a read-only check (`gh pr list` / an MR list
call) for whether a PR/MR already targets `rhdh-release-date-update`. Run it
now — read-only needs no gate. If one is already open, drop the "open a new
PR/MR" operation from the plan; pushing to the branch in step 7 updates it in
place automatically, since both forges reflect a branch's current head on its
open PR/MR without a separate "update" call.

## 6. Build one bundled plan and get approval

Invoke `/mutation-gate` and follow it. State every operation as one set —
`{source-revision}` below is the value step 4 captured for that target:

| Target | Operation | Command | Precondition | On failure |
|---|---|---|---|---|
| GitHub | Push rendered file to branch | `uv run --script scripts/release_dates.py apply --target github --github-rendered "$WORKDIR/rendered-github.yaml" --github-expect-revision {source-revision} --confirm` | Branch `rhdh-release-date-update` created or already exists at `redhat-developer/rhdh-plugin-export-overlays` | Report the API error, or a source-drift error if the base file moved since render; nothing on `main` is touched either way |
| GitHub | Open PR (skip if one is already open) | the exact `gh pr create` command from `/rhdh-forge` | Branch push above succeeded | Branch exists unopened; re-run this workflow to retry |
| GitLab | Push rendered file to branch | `uv run --script scripts/release_dates.py apply --target gitlab --gitlab-rendered "$WORKDIR/rendered-gitlab.yaml" --gitlab-expect-revision {source-revision} --confirm` | Branch `rhdh-release-date-update` created or already exists at `rhidp/rhdh-jira-lint` | Report the API error, or a source-drift error if the base file moved since render; nothing on `main` is touched either way |
| GitLab | Open MR (skip if one is already open) | the exact command from `/rhdh-forge` | Branch push above succeeded | Branch exists unopened; re-run this workflow to retry |

Show the rendered-file diff (old content vs. `$WORKDIR/rendered-*.yaml`) as the
preview for each push operation. Recovery for every operation here is the
same: close the PR/MR and/or delete the `rhdh-release-date-update` branch —
nothing lands on `main` without a separate human-reviewed merge. A source-drift
refusal means someone else changed the base file during this run — re-run from
step 3 rather than retrying the same `apply` command.

Always add one more row to the table that is a **report-only note, not an
operation requiring approval**: the pinned "RHDH x.y Release Information"
GitHub issue's current drift state (compare its table manually against the
source JSON). This skill does not edit that issue; it reports the drift so a
human can.

## 7. Execute and report

After approval, run the approved `apply` command(s), then the approved
`gh pr create` / MR-creation command(s) for any target that did not already
have one open. Report one outcome per operation, including:

- Every version's final `diff` state, skipped and invalid ones included:
  `match`, `invalid`, `skipped-tbd`, and `skipped-zstream`
- Every `incomplete` entry by version, naming its `missing_fields` and what
  the human has to supply for it to be written on a later run
- Any field `render` reported as skipped because the source did not supply it —
  the file kept its current value, which is correct, but say so rather than
  letting it look like a full rewrite
- Any planned release that exists but was not named in the request, and so was
  not checked this run
- The branch and, if opened or already open, the PR/MR URL for each forge
- The pinned-issue checklist note, always, regardless of whether the YAML
  files needed changes this run
