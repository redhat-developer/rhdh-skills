# Evidence sources

Collect the cheapest evidence first, then stop when the question is settled. A
citation is useful only when another reviewer can open it and see the same thing.

## Jira

The authoritative record for the report, its comments, links, versions, and
status.

| Fact | Where |
|---|---|
| Summary, description, comments | The issue itself |
| Fix and affects versions | `fixVersions`, `versions` |
| Duplicate, relates, blocks | `issuelinks` with the link type |
| Customer signals | `RHDH-Customer` label, customer fields, support links |
| Team and component | Team field and `components` |

Use `/rhdh-jira-api` for `acli` syntax, field IDs, JQL, and the REST/GraphQL
fallbacks. A read is safe; do not transition, comment, or link from this skill.

A JSON export is acceptable when `acli` is unavailable. The loader accepts the
REST envelope (`{"issues": [...]}`), a bare issue list, and the flatter records
`acli` emits. When the export omits descriptions or comments, the packet records
an evidence gap; absence in an export is not absence in Jira.

Inspect ADF inline cards and link marks too: their URLs can contain the only
reference to a canonical issue, fix, or customer case. Enrich candidate records
with creation dates, resolution, customer signals and full discussion before
canonical selection. Follow a tracker resolved as duplicate to its real target.

## GitHub forge

A merged pull request is the strongest affordable fix evidence. `/rhdh-forge` owns
the read mechanics and payload construction; this section states what a merged
change proves.

- Search by the Jira key in PR titles and bodies across the RHDH repositories, and
  also by the Jira keys this ticket links to or mentions: a fix can land under
  another bug's key while this ticket stays open. Record which key found the PR.
- Prefer the merge commit and the base branch over the PR description.
- Record the PR URL, merge state, merge date, and merge commit.
- A closed-but-unmerged PR is not a fix.
- A merged PR on `main` is not proof of a released fix. It becomes direct fix
  evidence only with a release that carries it.

`collect` reads a cache by default and uses read-only `gh pr view` and
`gh search prs` only when `--gh` is set. Neither path writes.

Per-query failures are retained in `searches`; cache-only collection is labeled
as such and unsearched linked keys are listed. Rate limits, permission failures,
invalid responses and cache misses are not successful negative searches. A search
hit is a lead: open the actual PR and verify exact state, diff and coverage.

## Release evidence

Use the release note, tag, or changelog that names the change. Record the exact
release and whether it is supported. The current release for a pass is supplied
with `--current-release` (for example `2.1.0`); `/rhdh-context` resolves the
target version, and `/rhdh-backport` owns backport mechanics and release-branch
rules. This skill only decides whether a fix is on the stream under review, and a
fix that exists only on an unsupported stream does not justify closing a report
against a supported one.

The fix release must also be no newer than the release under review. A fix that
first ships in a later release cannot close the ticket yet: record it, keep the
ticket unchanged, and abstain from an outward recommendation. Also verify the
exact release under review contains the change; numeric ordering alone cannot
prove ancestry across streams. No backport is proposed in this workflow;
separately requested critical customer backports belong to `/rhdh-backport`.

## Code

Open the current code path and check whether the failure can still happen. Cite
the file, symbol, and what the code does now. Code inspection is direct evidence
for `still_valid` when the defective path is unchanged, and for
`no_longer_valid` when the path was removed or replaced. It is not direct evidence
for `already_fixed` unless a release also carries the change.

These internal code findings do not produce still-valid/obsolete comments in
this milestone. Even direct proof of removed behavior is not an already-fixed
recommendation without the matching incorporated change and release evidence.

## Reproduction

A current-release reproduction is the strongest evidence for `still_valid` and a
valid basis for `no_longer_valid` when it fails to reproduce for a stated reason.
Record:

- the exact release and installation method;
- the platform and version;
- the steps, with the observed result;
- the full error text or a link to it.

Use `/rhdh-plugin-bug-fix` when the reproduction needs a build or a cluster. Do
not claim a reproduction you did not run. Such execution is a separate request,
not an automatic task for the user or a side effect of an abstention here.

## What is not evidence

- The ticket's age, by itself.
- An empty affects or fix version.
- Silence in the comments.
- A teammate's recollection without a citation.
- A similar title without the same failure or error signature.
- A lexical duplicate score alone; it ranks candidates, it does not decide.
- A closed duplicate that was never confirmed.
- A merged PR with no release, for an `already_fixed` close.

## Citation format

Each evidence item has four fields:

```json
{
  "type": "pr",
  "ref": "https://github.com/redhat-developer/rhdh/pull/1234",
  "why": "The merged change resolves the external S3 endpoint before the TechDocs build runs.",
  "strength": "direct"
}
```

`type` is one of `jira`, `pr`, `commit`, `release_note`, `code`, `doc`, `repro`,
or `comment`. `ref` is an actual HTTPS URL or a Jira issue key. Bare commit SHAs
and local pseudo-references cannot support outward closure proof. `why` states the inference in one
sentence. `strength` is `direct`, `strong`, or `supporting`.

An item missing `type`, `ref`, or `why` is dropped and counted as an evidence
gap and blocks closure until reconciled. That is deliberate: an uncited claim
cannot support a recommendation. Assessment flags and the offline verifier do
not independently establish an artifact's truth; reviewers must read it.

## Resolving conflicts

When sources disagree, prefer the more specific and more recent source, then
record the conflict in `notes`:

1. A current-release reproduction outranks a comment from an older release.
2. A merged commit outranks a PR description.
3. A release note outranks a guess about which release carries a fix.
4. Two independent citations that agree outrank one.
5. If the conflict cannot be resolved, record it locally and abstain without a
   comment or reproduction request. Do not hide contradictory evidence to pass
   a close gate.
