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

## GitHub forge

A merged pull request is the strongest affordable fix evidence.

- Search by the Jira key in PR titles and bodies across the RHDH repositories.
- Prefer the merge commit and the base branch over the PR description.
- Record the PR URL, merge state, merge date, and merge commit.
- A closed-but-unmerged PR is not a fix.
- A merged PR on `main` is not proof of a released fix. It becomes direct fix
  evidence only with a release that carries it.

`collect` reads a cache by default and uses read-only `gh pr view` and
`gh search prs` only when `--gh` is set. Neither path writes.

## Release evidence

Use the release note, tag, or changelog that names the change. Record the exact
release and whether it is supported. The current release for a pass is supplied
with `--current-release` (for example `2.1.0`); a fix that exists only on an
unsupported stream does not justify closing a report against a supported one.

## Code

Open the current code path and check whether the failure can still happen. Cite
the file, symbol, and what the code does now. Code inspection is direct evidence
for `still_valid` when the defective path is unchanged, and for
`no_longer_valid` when the path was removed or replaced. It is not direct evidence
for `already_fixed` unless a release also carries the change.

## Reproduction

A current-release reproduction is the strongest evidence for `still_valid` and a
valid basis for `no_longer_valid` when it fails to reproduce for a stated reason.
Record:

- the exact release and installation method;
- the platform and version;
- the steps, with the observed result;
- the full error text or a link to it.

Use `/rhdh-plugin-bug-fix` when the reproduction needs a build or a cluster. Do
not claim a reproduction you did not run.

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
or `comment`. `ref` is a URL, an issue key, a commit SHA, or a stable local
reference such as `repro:2.1.0/openshift-4.14`. `why` states the inference in one
sentence. `strength` is `direct`, `strong`, or `supporting`.

An item missing `type`, `ref`, or `why` is dropped and counted as an evidence
gap. That is deliberate: an uncited claim cannot support a disposition.

## Resolving conflicts

When sources disagree, prefer the more specific and more recent source, then
record the conflict in `notes`:

1. A current-release reproduction outranks a comment from an older release.
2. A merged commit outranks a PR description.
3. A release note outranks a guess about which release carries a fix.
4. Two independent citations that agree outrank one.
5. If the conflict cannot be resolved, use `unclear` and name what would settle
   it.
