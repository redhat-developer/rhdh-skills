# Fix version fields and sync rules

## Projects in scope

| Project | Role |
|---|---|
| RHIDP | Canonical metadata when the version exists here |
| RHDHPLAN | Planning Features; second canonical source |
| RHDHBUGS | Defects and CVEs; third canonical source |

RHDHSUPP is intentionally excluded.

## Canonical metadata

When the same version **name** exists in more than one project, metadata is taken
from the first project in this order that defines it: **RHIDP → RHDHPLAN →
RHDHBUGS**.

Other projects are updated to match: `description`, `startDate`, `releaseDate`,
`released`, `archived`.

Version **names** are matched case-sensitively, exactly as Jira stores them (for
example `1.11.0`, not `RHDH 1.11`).

## Fields

| Field | REST key | Notes |
|---|---|---|
| Name | `name` | Primary key across projects; must match exactly |
| Description | `description` | Optional text |
| Start date | `startDate` | `YYYY-MM-DD` |
| Release date | `releaseDate` | `YYYY-MM-DD`; set when marking released |
| Released | `released` | Boolean |
| Archived | `archived` | Prefer archiving over deleting when issues remain |

## Lifecycle state (per project)

Each fix version in a project is reported as exactly one lifecycle value:

| Lifecycle | Meaning |
|---|---|
| `unreleased` | `archived` is false and `released` is false — active/upcoming work |
| `released` | `released` is true and `archived` is false — GA or shipped stream |
| `archived` | `archived` is true — hidden from default pickers; takes precedence over `released` |

`list`, `status`, and `diff` all surface `lifecycle` per project. `diff` and `status`
also report `canonical_lifecycle` from the canonical project and whether each copy
`lifecycle_matches` it.

## Recent window (default for list, diff, and plan)

Bulk read commands default to a **recent window** so historical GA streams do not
drown out current release work. The default is **365 days** from today.

A version is **recent** when any in-scope project copy is:

- `unreleased` — always included (in-flight release work), or
- `released` or `archived` with a `releaseDate` or `startDate` on or after the
  cutoff.

Undated released/archived versions are treated as old and omitted unless
`--all-versions` is passed. `status VERSION` is never windowed — it always answers
for the name you gave.

Override the window:

```bash
uv run scripts/fixversions.py diff --json --within-days 180
uv run scripts/fixversions.py list --json --all-versions
```

## Release Feature date doc

Before `plan` or `ensure` builds create/update operations, the CLI looks up the
matching **RHDHPLAN release Feature** (`component = Release`, summary contains
the version, for example `RHDH 1.9.8 Release`). It parses the milestone table
in that issue's description — the same source `/rhdh-release-schedule` uses.

When `startDate` or `releaseDate` on the target metadata is still empty:

| Fix version field | Milestone tried (in order) |
|---|---|
| `releaseDate` | GA Announce, then Go/No Go & Push |
| `startDate` | Feature Freeze, then Code Freeze |

CLI flags (`--release-date`, `--start-date`) and values already on the canonical
fix version win. TBD cells are skipped. The plan records `date_sources` on each
operation when a field came from the release Feature (for example
`RHDHPLAN-1634 (GA Announce)`).

Pass `--no-release-doc` to skip the lookup.

## Closing the release Feature

Before transitioning the RHDHPLAN release Feature to **Closed**, run
`close-check VERSION`. The check confirms:

- A release Feature issue exists for the version (warning only if missing).
- The fix version is present in RHIDP, RHDHPLAN, and RHDHBUGS.
- Every copy is in the **released** lifecycle (`released` true, not archived).

When fix versions are still unreleased, use `ensure VERSION --released` (and
`--release-date` when known) to build an update plan, pass `/mutation-gate`, then
`apply`. Only close the release Feature after `close-check` reports
`ready_to_close_release_feature: true`.

### Next z-stream after close-out

For patch releases (`1.9.8`, `1.10.3`, …), `close-check` bumps the patch to
the next version and checks whether the RHDH **y-stream** (`1.9`, `1.10`, …)
is still supported via the Product Life Cycles API.

When support continues and the next patch lacks a fix version or release
Feature, the report sets `prompt_user: true`. Ask whether to create:

1. **Fix version** in all three projects — `ensure NEXT --json` (highest
   priority; engineering assigns issues to it immediately).
2. **RHDHPLAN release Feature** — `/rhdh-jira-create`, `Feature`, component
   `Release`, summary `RHDH NEXT Release`.

Pass `--skip-next-stream` on `close-check` to omit this follow-up.

## Create

`plan` emits `create` when the version name exists in at least one in-scope
project but is missing from another. The new version copies canonical metadata,
then applies release-doc dates for any empty date fields.

`ensure NAME` creates the version in every project when it is missing everywhere,
or fills in missing projects when it exists in at least one.

## Update

`plan` emits `update` when the version exists in a project but any synced field
differs from canonical.

## Delete and prune

Deletes are never implied by a plain `plan`. Pass `--prune` to include `delete`
operations for versions that exist in only one project (orphans).

Before delete, the CLI counts issues with that fix version. When the count is
non-zero, pass `--move-issues-to OTHER_VERSION` on `apply`, or archive instead.

## Related automation

Jira automation may cascade fix-version changes from Features to child Epics.
That behaviour affects **issues**, not project version lists. Read the Jira API
reference skill workflow rules before changing issue fix versions in the same
session.
