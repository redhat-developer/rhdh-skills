# Sync release dates — full run

Run every command from **this skill's directory** (the folder containing
`SKILL.md`), not the rhdh-skills repository root. Every `scripts/release_dates.py`
invocation uses `uv run --script` — the script declares `ruamel.yaml` through
PEP 723, and only `uv run --script` resolves that dependency without the
repository's own dev environment. A bare
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

If no entry across both targets is `stale` or `missing`, skip to step 7.
Report a clean run only when there are no `incomplete` or `invalid` entries;
otherwise report those unresolved entries along with the pinned-issue gap.

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
`apply` requires this revision and also checks the update branch's file against
it. If that branch already contains changes (including an earlier run's
unmerged update), stop and ask the human to merge or reconcile that PR/MR
first. Re-rendering from unchanged `main` alone cannot resolve branch drift.
An unreadable destination also stops the write; it never disables the lock.

## 5. Get the PR / MR creation command from `/rhdh-forge`

Compose the title and body for each required PR/MR. Invoke `/prose-editing`
once on the final prose in the `flavored` register before showing it or
passing it to `/rhdh-forge`. Use the edited text unchanged in the payload.

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
PR/MR" operation from the plan. Step 6's push updates it in place only if its
target file still matches the rendered baseline; otherwise the drift guard
refuses the push and the existing changes stay intact.

## 6. Build one bundled plan and get approval

Invoke `/mutation-gate` and follow it. State every operation as one set —
`{source-revision}` below is the value step 4 captured for that target:

| Target | Operation | Command | Precondition | On failure |
|---|---|---|---|---|
| GitHub | Push rendered file to branch | `uv run --script scripts/release_dates.py apply --target github --github-rendered "$WORKDIR/rendered-github.yaml" --github-expect-revision {source-revision} --confirm` | Branch `rhdh-release-date-update` created or already exists at `redhat-developer/rhdh-plugin-export-overlays` | Report the API error, or a source-drift error if the base file moved since render; nothing on `main` is touched either way |
| GitHub | Open PR (skip if one is already open) | the exact `gh pr create` command from `/rhdh-forge` | Branch push above succeeded | Preserve the push result and follow the creation-only recovery below |
| GitLab | Push rendered file to branch | `uv run --script scripts/release_dates.py apply --target gitlab --gitlab-rendered "$WORKDIR/rendered-gitlab.yaml" --gitlab-expect-revision {source-revision} --confirm` | Branch `rhdh-release-date-update` created or already exists at `rhidp/rhdh-jira-lint` | Report the API error, or a source-drift error if the base file moved since render; nothing on `main` is touched either way |
| GitLab | Open MR (skip if one is already open) | the exact command from `/rhdh-forge` | Branch push above succeeded | Preserve the push result and follow the creation-only recovery below |

Show the rendered-file diff (old content vs. `$WORKDIR/rendered-*.yaml`) as the
preview for each push operation. Recovery for every operation here is the
same: close the PR/MR and/or delete the `rhdh-release-date-update` branch —
nothing lands on `main` without a separate human-reviewed merge. A source-drift
refusal on the base means someone else changed it during this run — re-run
from step 3 rather than retrying the same `apply` command. A destination-drift
refusal requires human reconciliation of the existing PR/MR before re-rendering.
If branch creation succeeded before a later refusal, report that the branch
may now exist but its file was not updated.

If the file push succeeded but PR/MR creation failed, resume at step 5 rather
than repeating `apply`. Use `/rhdh-forge` to check whether creation succeeded
despite the reported error, and compare the branch's file with the approved
rendered file. If no PR/MR exists and the bytes still match, get approval
through `/mutation-gate` for a creation-only retry. Keep the original edited
prose and report the earlier push as already completed. If the branch differs
or cannot be checked, stop for human reconciliation; do not overwrite it.

Always add these **report-only notes, not operations requiring approval**:

- Compare the pinned "RHDH x.y Release Information" GitHub issue's table
  against the source JSON. Report its drift for a human to edit.
- Check existing pinned messages in `#forum-rhdh-releases` and
  `#rhdh-plugins-ecosystem` against the source dates. List stale message links
  and the dates a human needs to correct. If Slack access or message links
  are unavailable, explicitly report this check as not performed and ask the
  human to inspect the pins. Future bot posts do not repair existing pins.

Perform these checks even on the no-YAML-change path from step 3.

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
- The scope limitation: planned releases not named in the request were not
  checked or enumerated; do not claim to know which ones exist
- The branch and, if opened or already open, the PR/MR URL for each forge
- The pinned-issue and pinned-message checklist notes, including checks not
  performed, regardless of whether the YAML files needed changes this run
