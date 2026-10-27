# Workflow: Fetch GitHub PR Context

Fetch PR metadata, diff, linked issues, existing comments, and CI status from
GitHub. Produces the PR context that `review-code.md` analyzes.

## Script

Run the fetch script to collect all PR context in one call:

```bash
uv run scripts/fetch_pr_context.py <PR_URL_OR_NUMBER> [--repo owner/repo]
```

The path is relative to the skill directory.

The script accepts:

- A full URL: `https://github.com/owner/repo/pull/123`
- A number (detects repo from git remote): `123`
- A shorthand: `owner/repo#123`

Optional flags:

- `--repo owner/repo` — override repo detection
- `--no-diff` — skip diff (metadata-only queries)
- `--no-comments` — skip existing review comments
- `--no-issues` — skip fetching linked GitHub issues

Consume the full JSON output. Do not pipe through `head`, `tail`, or `grep`.

## PR context fields

The script prints one JSON object and nothing else. There is no envelope: these
fields are the whole document.

```
repository: "owner/repo"
changeRequest: {forge, number, headSha, baseRef, headRef, title, body, author, state, url, labels}
files: [{path, additions, deletions}, ...]
totalAdditions, totalDeletions
diff: "full unified diff text"
linkedIssues: [{number, title, body, labels, state}, ...]
jiraKeys: ["RHIDP-1234", ...]
existingComments: [{user, path, line, body, createdAt}, ...]
existingReviews: [{user, state, body}, ...]
ciStatus: "pass" | "fail" | "pending" | "unknown"
```

## Linked issues

`linkedIssues` carries the title, body, labels, and state of each GitHub issue
the PR body references — enough for most reviews. When a review needs the full
issue detail, including its comment thread and resolved workspace, invoke
`/rhdh-forge` by name with the issue reference. Do not add issue parsing to this
workflow.

When `linkedIssues` is empty, ask once whether there is a spec or issue to
judge against. If the author points at none, the PR body is the contract. Carry
that choice forward as `specSource` — the linked issue bodies, or the PR body —
into `/code-review` Spec. Spec still runs; the review does not wait on an issue.

## Jira keys

The script extracts Jira keys (for example, `RHIDP-1234`) from the PR body but
does not fetch them. When Jira detail affects the review, read the issues
with your Jira tool and use what it returns. Otherwise retain the keys and
continue. Do not select a Jira transport or inspect Jira credentials from this
workflow.

## CI status

`ciStatus` comes from `gh pr checks`. When it is `unknown`, invoke `/rhdh-forge`
to confirm against `gh run list --branch` before treating CI as missing or
failed. `/rhdh-forge` owns failed-log reads.

## After fetching

Proceed to `review-code.md`. Carry the complete context forward. Downstream
workflows read these fields by name, including `specSource`.
