# Sync release dates — full run

Run every command from **this skill's directory** (the folder containing
`SKILL.md`), not the rhdh-skills repository root.

## 1. Capability gate

```bash
uv run scripts/release_dates.py check
```

Fails closed if `gh auth status` or `glab auth status --hostname
gitlab.cee.redhat.com` fails. Stop and tell the human to run
`/setup-rhdh-skills` (Jira/GitHub/GitLab authentication) — do not proceed on a
missing capability.

## 2. Get source-of-truth dates

Invoke `/rhdh-release-schedule` for every RHDH version it reports as active
or planned (or the single version the human named, if the request scoped one).
Transcribe its answer — including which source produced each date — into the
source-JSON shape in `references/target-schemas.md`, and write it to a temp
file, e.g. `/tmp/rhdh-release-dates.json`.

This step is not scriptable: `/rhdh-release-schedule` itself reads Jira and a
spreadsheet through an agent, not a fixed API call. Everything after this
step is deterministic.

Three things go wrong here if you transcribe on autopilot. The field mapping is
in `references/target-schemas.md` — read it before building the JSON:

- `ga_push` is the **GA announce** date, not Go/No Go & Push.
- `backstage_version` is **not** something `/rhdh-release-schedule` reports.
  Read it from the target file's existing entry, or ask the human for a release
  being added. Omit the field rather than guessing — the script preserves what
  is already in the file and reports the omission, but a guessed value reaches
  third-party plugin owners as the Backstage version to target.
- Leave z-stream versions such as `1.10.5` out. Both files track `x.y.0` only.

## 3. Diff

```bash
uv run scripts/release_dates.py diff --source-json /tmp/rhdh-release-dates.json
```

Read the JSON report. Each target (`github`, `gitlab`) lists one entry per
version with `state`:

| State | What to do |
|---|---|
| `match` | Nothing |
| `stale` | Fix it — `desired` holds the corrected fields |
| `missing` | Add it — absent from the file and fully specified |
| `incomplete` | Absent, but the source lacks `missing_fields`. Do not write a partial entry: ask the human for those values and re-run, or report it as needing a human |
| `skipped-tbd` | Feature Freeze undecided upstream — leave alone |
| `skipped-zstream` | Not an `x.y.0` release; neither file tracks it |

Every state is named in the final report, including the skipped ones.

If no entry across both targets is `stale` or `missing`, skip to step 7 and
report a clean run — still naming any `incomplete` entries and the
pinned-issue gap.

## 4. Render

For each target with at least one `stale` or `missing` entry:

```bash
uv run scripts/release_dates.py render --target github \
  --source-json /tmp/rhdh-release-dates.json --output /tmp/rendered-github.yaml
uv run scripts/release_dates.py render --target gitlab \
  --source-json /tmp/rhdh-release-dates.json --output /tmp/rendered-gitlab.yaml
```

`render` regenerates the whole file from source-of-truth every time — never a
partial patch — so re-running this workflow is always safe. It never touches
a version absent from the source JSON, so historical entries are untouched.

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

Invoke `/mutation-gate` and follow it. State every operation as one set:

| Target | Operation | Command | Precondition | On failure |
|---|---|---|---|---|
| GitHub | Push rendered file to branch | `scripts/release_dates.py apply --target github --github-rendered /tmp/rendered-github.yaml --confirm` | Branch `rhdh-release-date-update` created or already exists at `redhat-developer/rhdh-plugin-export-overlays` | Report the API error; nothing on `main` is touched |
| GitHub | Open PR (skip if one is already open) | the exact `gh pr create` command from `/rhdh-forge` | Branch push above succeeded | Branch exists unopened; re-run this workflow to retry |
| GitLab | Push rendered file to branch | `scripts/release_dates.py apply --target gitlab --gitlab-rendered /tmp/rendered-gitlab.yaml --confirm` | Branch `rhdh-release-date-update` created or already exists at `rhidp/rhdh-jira-lint` | Report the API error; nothing on `main` is touched |
| GitLab | Open MR (skip if one is already open) | the exact command from `/rhdh-forge` | Branch push above succeeded | Branch exists unopened; re-run this workflow to retry |

Show the rendered-file diff (old content vs. `/tmp/rendered-*.yaml`) as the
preview for each push operation. Recovery for every operation here is the
same: close the PR/MR and/or delete the `rhdh-release-date-update` branch —
nothing lands on `main` without a separate human-reviewed merge.

Always add one more row to the table that is a **report-only note, not an
operation requiring approval**: the pinned "RHDH x.y Release Information"
GitHub issue's current drift state (compare its table manually against the
source JSON). This skill does not edit that issue; it reports the drift so a
human can.

## 7. Execute and report

After approval, run the approved `apply` command(s), then the approved
`gh pr create` / MR-creation command(s) for any target that did not already
have one open. Report one outcome per operation, including:

- Every version's final `diff` state, skipped ones included: `match`,
  `skipped-tbd`, and `skipped-zstream`
- Every `incomplete` entry by version, naming its `missing_fields` and what
  the human has to supply for it to be written on a later run
- Any field `render` reported as skipped because the source did not supply it —
  the file kept its current value, which is correct, but say so rather than
  letting it look like a full rewrite
- The branch and, if opened or already open, the PR/MR URL for each forge
- The pinned-issue checklist note, always, regardless of whether the YAML
  files needed changes this run
