# What the old lint job did, and who owns it now

The deployed `rhdh_jira_lint.py` does more than hygiene checks. This is the
inventory, so nothing disappears silently when the hygiene half moves here.

| Old responsibility | Current owner | Notes |
|---|---|---|
| Per-assignee hygiene findings, sent as Slack DMs | **This skill** | Findings are fixed and recorded on the issue instead of messaged. The Slack DM becomes one summary of what was done |
| Release-date parsing from `release_calendar.yaml` | **This skill**, via `/rhdh-release-schedule` | Dates are discovered during the run; the file is an optional cache |
| Freeze-date and release-note rules | **This skill** | The rule set in [rules.md](rules.md) |
| Stale and multi-fix-version checks | **This skill** | Multi-fix-version is a rule; staleness is a candidate filter, not a finding (see parity notes in rules.md) |
| Feature Freeze announcement, ~5 months out | `/rhdh-release-announce` + `/rhdh-release-schedule` | Already a skill pair; this skill does not draft channel messages |
| Backstage version-bump announcement | **Gap** | The old script watches `backstage.json` in `redhat-developer/rhdh` and compares it with `backstage_version` in the calendar. No skill owns it yet |
| Docs-review queue posted to `#forum-rhdh-releases` | **Gap** | The old script selects Features and Bugs in active releases whose Release Note fields are ready for the docs team. Reading that queue is cheap; posting it to a channel has no owner |
| SoS reminder to `#rhdh-team-leads` | **Gap, and not lint** | It rides in the same weekly job but is an operations reminder, not issue hygiene |

The three gaps are deliberate: this skill owns issue remediation, and widening it
to channel broadcasts would make one trigger phrase answer several unrelated
utterances. Decide them separately — either a small read-only workflow here that
returns the queue, or a dedicated notifier skill.

## What "the bot runs the skill" means

The runner needs to:

1. authenticate Jira;
2. invoke this skill for the scope it is responsible for;
3. deliver the skill's summary to the people who need it.

It does not prepare a calendar, build an operation policy, choose which fields are
allowed, or re-implement any rule. Those live here.
