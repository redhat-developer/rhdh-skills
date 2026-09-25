---
name: rhdh-release-date-update
description: >-
  Diffs RHDH milestone dates (Feature Freeze, Code Freeze, GA, targeted
  Backstage version) from /rhdh-release-schedule against release-schedule.yaml
  in redhat-developer/rhdh-plugin-export-overlays and release_calendar.yaml in
  rhidp/rhdh-jira-lint (GitLab CEE), then opens a pull/merge request that
  corrects stale dates and adds missing release entries. Use for "sync the
  release date files", "update release-schedule.yaml", "update
  release_calendar.yaml", "the RHDH schedule changed, propagate it", "check
  release-schedule.yaml is current", "keep plugin-owner release dates in
  sync", or a downstream reminder or announcement that landed with the wrong
  freeze date. Never edits chat announcements or issue pinning/content
  directly — those stay on their owning workflow until /rhdh-forge covers
  issue writes.
---

# RHDH release date update

Keep `release-schedule.yaml` (GitHub) and `release_calendar.yaml` (GitLab CEE)
in sync with the authoritative RHDH release schedule. Both files drive
automation the plugin ecosystem already depends on: `release-schedule.yaml`
feeds `notify-3rd-party-owners.yaml`'s GitHub-issue reminders, and
`release_calendar.yaml` feeds the `rhdh-jira-lint` bot's Slack posts to
`#forum-rhdh-releases` and `#rhdh-plugins-ecosystem`. A stale date in either
file produces a wrong reminder or a wrong Slack message with no review step —
that is what this skill exists to prevent.

## Scope

In scope: `release-schedule.yaml` and `release_calendar.yaml` — correcting
stale entries and adding entries for newly-scheduled releases.

Out of scope, reported as a checklist item instead of fixed:

- The pinned "RHDH x.y Release Information" GitHub issue in
  `rhdh-plugin-export-overlays`. `/rhdh-forge` does not yet build payloads for
  issue edit, pin, unpin, or close, so this skill only reports drift there —
  it does not fix it. Revisit once `/rhdh-forge` covers those operations.
- Slack messages in `#forum-rhdh-releases` / `#rhdh-plugins-ecosystem`. The
  `rhdh-jira-lint` bot posts these automatically, driven entirely by
  `release_calendar.yaml`'s contents on its own weekly schedule — once that
  file is correct, the messages follow without further action.
- Any release whose Feature Freeze date is not yet decided (`TBD` upstream).
  Leave it untouched and report it, never write a placeholder — both target
  files are parsed with `datetime.strptime(..., "%Y-%m-%d")` downstream, and a
  placeholder crashes that parse on its next scheduled run.
- Historical, already-GA'd release entries. Only ever touch a version that
  `/rhdh-release-schedule` currently reports as active or planned; never
  prune old entries.

## Workflow

Load `workflows/sync-release-dates.md` — it covers the full run: the
capability gate, composing with `/rhdh-release-schedule` for source-of-truth
dates, running `scripts/release_dates.py`, composing with `/rhdh-forge` for
the PR and MR creation commands, and the bundled `/mutation-gate` approval.

Load `references/target-schemas.md` for the exact field mapping of each
target file and the source-JSON shape `scripts/release_dates.py` expects.

## Boundary with the neighbouring skills

- Source-of-truth dates come from `/rhdh-release-schedule` by name — this
  skill never reads Jira or the schedule spreadsheet itself.
- `gh pr create` / `glab mr create` commands come from `/rhdh-forge` by name.
  This skill's own script pushes the branch and file content directly (a
  plain git content-API write, not a forge social interaction) but never
  constructs a PR/MR command itself.
- Every write — branch push and PR/MR creation alike — goes through
  `/mutation-gate` as one bundled plan per run, approved once.
- Drafting the Slack message that announces a freeze is
  `/rhdh-release-announce`; this skill never drafts or posts one.

## Completion

Complete when `scripts/release_dates.py diff` has run against both target
files, every non-`match`, non-`skipped-tbd` entry has a proposed fix in the
approved plan, the plan was approved before any push happened, and every
operation in the plan — branch push, and PR/MR creation once `/rhdh-forge`'s
command was executed — has a reported outcome. A version skipped as `TBD` is
named as skipped, never silently omitted from the report. The pinned-issue
gap is always named in the report, even on a run where both YAML files
already matched.
