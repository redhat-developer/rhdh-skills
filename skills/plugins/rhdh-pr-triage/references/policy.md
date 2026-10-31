# Triage Decision Policy

Decision rules for Renovate and Dependabot PRs. Apply top-to-bottom within each
section; the first matching rule wins.

## Preconditions (apply before any section)

| Condition | Decision | Reason |
|-----------|----------|--------|
| PR is draft | skip | Draft PR |
| PR has conflicts, author is `renovate[bot]` | rebase | `@renovatebot rebase` |
| PR has conflicts, author is `dependabot[bot]` | recreate | `@dependabot recreate` |
| Same dependency from both bots | merge Renovate, close Dependabot | Renovate title includes `[security]`, preserving the reason in commit history |

## Main branch

Main is a development branch — major version bumps are allowed.

| Condition | Decision | Reason |
|-----------|----------|--------|
| CI green | approve+merge | CI passing |
| CI pending | skip | Waiting for CI |
| CI failing | skip | CI failing |

## Release branch (release-x.y)

Look up the release state for the corresponding RHDH minor version by invoking
`/rhdh-release-schedule`. Unless told otherwise, never guess release dates or rely on persisted memory —
release states may change frequently and a stale assumption can destabilize an
imminent GA. Always use the live result.

| Condition | Decision | Reason |
|-----------|----------|--------|
| RHDH x.y is EOL | close | Closing — RHDH x.y is end of life |
| Major version bump | close | No major bumps on release branches |
| Go repo: `go` directive bumped in go.mod, PR has `[security]` label | flag | Human review — security + go directive bump |
| Go repo: `go` directive bumped in go.mod | close | Go directive frozen on release branches |
| Go repo: `toolchain` non-patch bump, PR has `[security]` label | flag | Human review — security + toolchain bump |
| Go repo: `toolchain` non-patch bump | close | Only toolchain patch bumps on release branches |
| Release state is TBD or unknown | unknown | Cannot determine CF/FF/GA state for x.y.z — report as undecidable |
| At CF or FF | hold | /hold until x.y.z is out |
| Past GA announce but tag not yet pushed | hold | /hold if not already held — still waiting on x.y.z tag |
| Already held (`do-not-merge/hold`), no state change since last triage | skip | Still waiting on x.y.z (no action needed, already held) |
| GA'd — git tag exists AND release notes confirm z-stream | unhold+approve+merge | x.y.z released |

### Unknown release state

When `/rhdh-release-schedule` returns TBD for all milestones of a z-stream, the
triage cannot determine whether the release is at CF, FF, or pre-freeze. Do not
guess — report the PR as **undecidable** with the reason "release state unknown
for x.y.z" and let the human decide. The summary table counts these separately
as "unknown (release state TBD)".

### Verifying GA

To confirm a z-stream has GA'd, check all of:

1. `git ls-remote --tags` against **each repo that has open PRs** for the
   expected tag (e.g. `1.10.5`). Tags in these repos do not carry a `v` prefix.
   The match must be **exact**: a tag named `redhat-developer-hub-2.1.0` is a
   chart-version tag, not the `2.1.0` release tag — the upstream rhdh-chart repo
   bumps the chart version for every changed chart, so these tags exist
   independently of the RHDH release cycle. Only `refs/tags/<x.y.z>` counts.
   A tag present in one repo but absent in another means the release is not
   fully rolled out — hold PRs in repos where the tag is missing.
2. Release notes: check **both** pages for a section covering that z-stream —
   a security-only patch may appear only on the second page:
   - `https://docs.redhat.com/en/documentation/red_hat_developer_hub/{major.minor}/html/red_hat_developer_hub_release_notes/fixed-issues`
   - `https://docs.redhat.com/en/documentation/red_hat_developer_hub/{major.minor}/html/red_hat_developer_hub_release_notes/fixed-security-issues`

   A match on either page confirms the z-stream is published.
3. **Go repos (rhdh-operator, rhdh-must-gather on release-2.y+):** the
   `VERSION` variable in the `Makefile` on the release branch must show the
   **next** z-stream (e.g. `0.10.5` after tagging `1.10.4`). This bump happens
   right after the tag is pushed; if the version still shows the just-released
   z-stream, the branch is not ready for new merges. For `release-1.y` branches
   the Makefile uses `0.y.z`; for `release-2.y+` branches it uses the matching
   `2.y.z`.

   Check with:
   ```
   gh api 'repos/redhat-developer/rhdh-operator/contents/Makefile?ref=release-x.y' \
     --jq '.content' | tr -d '\n' | base64 -d | grep 'VERSION ?='
   ```

All must confirm before unholding.

## Go repo policy

The `go` directive and `toolchain` rules above apply to every repo that ships a
Go binary. Currently:

- **rhdh-operator** — all branches
- **rhdh-must-gather** — `main` and `release-2.y+` branches only (the must-gather
  was rewritten in Go; `release-1.10` and earlier are still shell-based and have
  no `go.mod`)

When `go_directive_bumped` or `go_toolchain_bumped` is true in a PR from one of
these repos on a release branch, close it per the rules above — unless the PR
also carries a `[security]` label, in which case flag it for human review
instead of closing. The security fix may need to land via a manual patch that
does not bump the directive.

To avoid spamming on repeated triage runs, only post a new flag comment when the
PR's actual diff has changed since the last flag comment — not merely when
Renovate rebased the branch. Renovate force-pushes on rebase, creating a new
commit SHA without changing the dependency update itself.

To detect a meaningful diff change: compare the dependency target version in the
current PR diff against the version recorded in the last flag comment. If the
versions match, the rebase did not change the update — skip silently. If they
differ, Renovate updated the PR to a newer dependency version — post a new flag.

Flag comments must always include the dependency target version (e.g.
"golang.org/x/net v0.62.0") so subsequent triage runs can compare.

If a previous triage run already left a flag comment and the dependency version
has not changed since, skip the PR silently.

On main, Go directive and toolchain bumps are allowed and follow normal
main-branch rules.

## Chart repo special rules

These apply in addition to the main/release branch rules above.

| Condition | Decision | Reason |
|-----------|----------|--------|
| Lint CI fails, dep is a chart dependency | bump | `/bump <chart> <minor\|patch>` per chart folder |
| Multiple chart folders modified | bump (one per chart) | One `/bump` comment per affected chart |
| GH Actions update (not a chart dep) | normal rules | No chart bump needed |

The bump level matches the semver level of the dependency version change:
minor dep bump gets `/bump <chart> minor`, patch gets `/bump <chart> patch`.

## rhdh-local branch model

rhdh-local uses `dev` as its development branch. The `main` branch is kept
stable per a PM requirement and does not receive bot PRs. Treat PRs targeting
`dev` in rhdh-local the same as PRs targeting `main` in other repositories.

## Merge strategy

All PR merges use the **squash** strategy (`gh pr merge --squash`).

## CI status rules

All required checks must be green. Skip `tide` when evaluating CI status on
repos that use Prow — `tide` is a merge gate, not a quality signal.

CI status must be verified live (`gh pr checks`) before executing any decision
that depends on it. The status returned by the listing script is a snapshot that
can go stale within minutes — never treat it as authoritative for execution.
