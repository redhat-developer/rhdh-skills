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
| Minor bump of a Go builder image (e.g. `go-toolset`) | normal rules | Build-time image — minor allowed on release branches |
| Minor version bump, PR has `[security]` label | normal rules | Security fix — minor allowed on release branches |
| Minor version bump | close | Release branches take patch-level updates only |
| Go repo: `go` directive bumped in go.mod, PR has `[security]` label | flag | Human review — security + go directive bump |
| Go repo: `go` directive bumped in go.mod | close | Go directive frozen on release branches |
| Go repo: `toolchain` non-patch bump, PR has `[security]` label | flag | Human review — security + toolchain bump |
| Go repo: `toolchain` non-patch bump | close | Only toolchain patch bumps on release branches |
| Go pseudo-version (`v0.0.0-…`) bump, PR has `[security]` label | normal rules | Security fix — pseudo-version allowed on release branches |
| Go pseudo-version (`v0.0.0-…`) bump | close | Pseudo-versions stay off release branches |
| Release state is TBD or unknown | unknown | Cannot determine CF/FF/GA state for x.y.z — report as undecidable |
| At CF or FF | hold | /hold until x.y.z is out |
| Past GA announce but tag not yet pushed | hold | /hold if not already held — still waiting on x.y.z tag |
| Already held (`do-not-merge/hold`), no state change since last triage | skip | Still waiting on x.y.z (no action needed, already held) |
| GA'd — git tag exists AND release notes confirm z-stream | unhold+approve+merge | x.y.z released |

### Patch-level only on release branches

A `release-x.y` branch ships to customers and stays stable between z-streams, so
it takes patch-level updates only. A minor or major bump there is closed, not
held and not bumped — holding it leaves a PR nobody intends to merge, and a
`/bump` publishes the change into the release. Two narrow exceptions follow: a
security fix, and a Go builder image.

This rule is not chart-specific and not repo-specific. It holds in rhdh-operator,
rhdh-chart, rhdh-must-gather and rhdh-local alike: none of them takes an ordinary
minor bump on a release branch. The chart bump rules below change only how a
patch-level change is landed, never whether a minor is allowed.

This applies to every dependency class: GitHub Actions versions, Go modules,
container image tags, and chart values. A digest pin (`to <sha>`) carries no
version and is not a bump; a move such as `v1.7.0` to `v1.9.0`, `8.22.0` to
`8.23.0`, or `v1.19.x` to `v1.20.2` is a minor.

Read the diff, not the script's `semver_level`. That field only recognises an
`x.y.z` to `x.y.z` or `from vX to vY` shape, so image tags, action versions, and
anything with a partial version come back as `unknown`. A `1.7.0` to `1.9.0`
skip is still a minor.

Closing is for the version arithmetic, not for a security fix. A minor bump
carrying `[security]` is not closed: it follows the ordinary release-branch rules
and merges once the branch is open, because refusing it would leave a CVE unfixed
on a supported branch. The exception is narrow — the label has to be on the PR,
and it covers the security update itself, not whatever else the bump drags in.

Go builder images are the other exception. An image such as `ubi9/go-toolset` or a
`golang:1.x` builder stage compiles the binary and does not ship in the artifact
a customer installs, so a minor bump to one — `go-toolset:1.24` to
`go-toolset:1.25` — is allowed on a release branch and follows the ordinary
release-branch rules rather than this one. It is the `FROM` of the build stage
that qualifies. A runtime or final base image (`ubi-minimal`, `distroless`, a
runtime stage) is shipped and stays patch-only.

A minor bump landing in this category is itself the signal: Renovate should not be
raising one there. Say so in the close comment and point the update at the
development branch, so the gap gets fixed instead of recurring every cycle. The
development branch is `main`, or `dev` for rhdh-local; minor bumps are welcome
there.

Example: rhdh-chart #672 moved the `curl` test image from `8.22.0` to `8.23.0` on
`release-2.1`. It carried no `[security]` label, so it should have been closed
rather than treated as a chart bump. The same run merged three more non-security
minors in rhdh-chart — #709 (`chart-releaser-action` v1.7.0 to v1.9.0), #682
(`chainguard/actions/setup-gitsign` v1.6.41 to v1.8.1) and #679 (`setup-tombi`
v1.8.4 to v1.11.2). The two security minors that merged, rhdh-operator #4012 and
#3938, are correct under the exception. Catching the shape in one repository is
not evidence that the others are clean: check every PR on every release branch
against this rule.

### Go pseudo-versions

A pseudo-version is commit-shaped: `v0.0.0-20260114153012-abcdef123456`. Renovate
words it as a digest bump — "update k8s.io/utils digest to ca04ba5" — and it names
a commit rather than a release. The upstream module published no tag, so there is
no semver contract, no changelog, and nothing to reason about when the next commit
moves it again.

That is fine on `main` and on rhdh-local's `dev`, where the code is expected to
track upstream. It is wrong on a release branch, where the shipped binary should
change only for a reason someone wrote down: close the PR there. The one exception
is a security-labelled pseudo-version bump, which follows the ordinary
release-branch rules rather than this one.

Detect it from the diff or the title, not from `semver_level`: a
`v0.0.0-<14-digit timestamp>-<12 hex characters>` on the changed `go.mod` line, or
`digest to <sha>` in the title. A real tag such as `v0.62.0` is not a
pseudo-version. When the same PR also bumps the `go` directive, the directive rows
above win, because the table is applied top to bottom.

This rule arrived after the fact: `k8s.io/utils` (#3968),
`github.com/openshift/api` (#3864) and `golang.org/x/exp` (#3865) were all merged
to `release-2.1` as digest bumps and would be closed under it.

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
| Lint CI fails, dep is a chart dependency, patch-level bump | bump | `/bump <chart> patch` per chart folder |
| Multiple chart folders modified | bump (one per chart) | One `/bump` comment per affected chart |
| GH Actions update (not a chart dep) | normal rules | No chart bump needed |

The release-branch rules run first. A minor or major dependency bump on
`release-x.y` is closed before this section is reached, so `/bump` is only ever
reached by a patch-level change and always takes `patch`. On the development
branch the bump level follows the semver level of the dependency change: a minor
dep bump gets `/bump <chart> minor`, a patch gets `/bump <chart> patch`.

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
