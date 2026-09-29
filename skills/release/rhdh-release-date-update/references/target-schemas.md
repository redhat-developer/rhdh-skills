# Target file schemas and the source-JSON shape

## Source-JSON (what you build from /rhdh-release-schedule's answer)

Invoke `/rhdh-release-schedule` for every version that is currently active or
planned. Transcribe its answer into this shape and write it to a temp file —
`scripts/release_dates.py diff --source-json <path>` reads it:

```json
{
  "2.1.0": {
    "feature_freeze": "2026-09-22",
    "code_freeze": "2026-10-13",
    "ga_push": "2026-10-28",
    "backstage_version": "1.54.0",
    "source": "RHDHPLAN release Feature RHDHPLAN-123"
  },
  "2.2.0": {
    "feature_freeze": "TBD",
    "code_freeze": null,
    "ga_push": null,
    "backstage_version": "1.58.0",
    "source": "RHDH release schedule spreadsheet, 2027 tab"
  }
}
```

`feature_freeze` of `null`, `""`, `"TBD"`, or `"tbd"` marks the whole release
as not-yet-decided — the script skips every field for that version rather
than writing a partial or placeholder entry. `source` is carried through for
the plan's preview text; it is never written into either target file.

### Where each field comes from

`/rhdh-release-schedule` does not use these key names, and it does not carry
the Backstage version at all. Map its answer deliberately:

| `/rhdh-release-schedule` reports | Source-JSON key |
|---|---|
| Feature Freeze | `feature_freeze` |
| Code Freeze | `code_freeze` |
| GA announce | `ga_push` |
| Go/No Go & Push | *nothing — do not use it* |
| Docs Freeze, Docs Input Freeze | *nothing — neither file has a column* |

`ga_push` is the **GA announce** date, not Go/No Go. `release_calendar.yaml`
says so in its own header comment: `ga_push = GA announce date (public GA)`.
Picking Go/No Go here puts a wrong date into the file that drives the Slack
posts.

`backstage_version` has no source in `/rhdh-release-schedule`. Get it from the
target file's existing entry for a release already listed, or ask the human for
a release being added. Never infer it from the version number and never guess:
the value reaches third-party plugin owners as the version they are told to
target.

### Never invent a value

A field the source does not supply is not written. On a release already in the
file the current value stands; the script reports the field as unsupplied
rather than overwriting it. A release *absent* from the file is only created
when every field that file requires is supplied — `backstage_version` and
`feature_freeze` for GitHub, all four for GitLab. Otherwise `diff` reports it
as `incomplete` with the missing field names and writes nothing.

### Versions the target files do not track

Both files track minor releases only — every entry is `x.y.0`. The active
release query also returns z-streams such as `1.10.5`; the script reports those
as `skipped-zstream` and never writes them. Do not add z-stream versions to the
source JSON.

### `diff` states

| State | Meaning |
|---|---|
| `match` | Every supplied field already agrees with the file |
| `stale` | A supplied field differs; the fix is in `desired` |
| `missing` | Absent from the file and fully specified, so it can be added |
| `incomplete` | Absent from the file but the source lacks `missing_fields` |
| `skipped-tbd` | Feature Freeze is not yet decided upstream |
| `skipped-zstream` | Not an `x.y.0` release, so neither file tracks it |

## `release-schedule.yaml` (GitHub — `redhat-developer/rhdh-plugin-export-overlays`)

A YAML list under `releases:`, one dict per version:

```yaml
releases:
  - rhdh-version: "2.1.0"
    backstage-version: "1.54.0"
    feature-freeze: "2026-09-22"
```

Only three fields exist here. `code_freeze` and `ga_push` from the source
JSON are not written to this file — it has no columns for them.

Consumed by `.github/workflows/notify-3rd-party-owners.yaml`, which opens a
per-plugin-owner GitHub issue 13–19 days before `feature-freeze`.

## `release_calendar.yaml` (GitLab CEE — `rhidp/rhdh-jira-lint`)

A YAML mapping under `releases:`, keyed by version string:

```yaml
releases:
  "2.1.0":
    feature_freeze: "2026-09-22"
    code_freeze: "2026-10-13"
    ga_push: "2026-10-28"
    backstage_version: "1.54.0"
```

All four source-JSON date/version fields map directly here.

Consumed by `rhdh_jira_lint.py`'s scheduled GitLab CI job, which parses every
`feature_freeze` with `datetime.strptime(value, "%Y-%m-%d")` — a non-date
string in this field crashes that job's next run. This is the file the
`#forum-rhdh-releases` / `#rhdh-plugins-ecosystem` Slack posts are driven
from; treat every write to it as higher-stakes than the GitHub file.

## Quoting convention

Both files consistently double-quote every version key and every date/version
value. `scripts/release_dates.py render` wraps every value it writes in
`ruamel.yaml.scalarstring.DoubleQuotedScalarString` to match — an unquoted
`2.3.0` would still parse back as the same string, but it reads as
inconsistent with the rest of the file to a reviewer, and an unquoted numeric-
looking value elsewhere in YAML can silently become a float.

## Known cosmetic gap

Both files separate existing entries with a blank line. `render` appends new
entries without one — ruamel's comment/blank-line model attaches to the node
that follows, and forcing separator blank lines onto a newly-created node
added meaningfully more code for a purely cosmetic gap. A reviewer sees
slightly tighter spacing around a newly added entry; the YAML itself is valid
and round-trips correctly either way.
