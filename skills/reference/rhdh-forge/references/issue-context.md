# Issue context

Resolve an issue reference, fetch its detail, and locate the workspace it
belongs to. `scripts/fetch_issue_context.py` performs all of this for GitHub and
prints the issue fields as one JSON object; the rules below are the same logic
for a caller that needs to parse without a network call, that needs to explain a
result, or that is holding a GitLab reference instead.

## Which forge

| Reference | Forge |
|---|---|
| `github.com/...`, or `owner/repo#123` | GitHub, read with `gh` |
| Any other host in the URL, such as `gitlab.cee.redhat.com/...` | GitLab, read with `glab` |
| `!123`, or `group/project!123` | GitLab merge request |
| Bare `#123` or `123` in a checkout | Whichever host `git remote -v` names |

GitLab numbers a project's issues and merge requests separately, and both
counters restart per project. `#123` and `!123` in the same project are
different objects.

## Parse a GitHub reference

Accept any of these and normalize to a repository plus number:

| Input | Example | Extraction |
|---|---|---|
| Full URL | `https://github.com/redhat-developer/rhdh-plugins/issues/607` | Owner, repository, and number from the path |
| URL without scheme | `github.com/backstage/community-plugins/issues/3574` | Same, prepending `https://` |
| URL with fragment or query | `.../issues/607#issuecomment-123` | Strip fragment and query, then extract |
| Shorthand | `redhat-developer/rhdh-plugins#607` | Split on `#` |
| Bare number in a checkout | `#123` | Resolve the repository from `git remote -v` |

1. If the input contains `github.com/`, read `/<owner>/<repo>/issues/<number>`
   from the path.
2. If the input matches `<owner>/<repo>#<number>`, split it directly.
3. If the input matches `#\d+` or a bare number, resolve the repository from the
   current checkout.
4. If none match, the input is not a GitHub issue. Try the GitLab rules below,
   and if those fail too, hand it back so the caller can try its Jira parser.

Construct the canonical URL from the resolved owner, repository, and number.
Never store the raw input as the URL.

### Repository profile

| Reference contains | Profile |
|---|---|
| `rhdh-plugins`, but not `community-plugins` | rhdh-plugins |
| `community-plugins` | community-plugins |
| Neither, or a bare number | Detect from `git remote -v` |

## Parse a GitLab reference

A GitLab path is a namespace of one or more groups plus the project, so
`rhidp/rhdh` and `releng/konflux/tooling` are both valid. Split on `/-/`: what
precedes it is the full project path, and what follows names the object.

| Input | Example | Extraction |
|---|---|---|
| Issue URL | `https://gitlab.cee.redhat.com/rhidp/rhdh/-/issues/42` | Project path before `/-/`, number after `issues/` |
| MR URL | `https://gitlab.cee.redhat.com/rhidp/rhdh/-/merge_requests/17` | Same, number after `merge_requests/` |
| URL with fragment or query | `.../-/merge_requests/17#note_9` | Strip fragment and query, then extract |
| Issue shorthand | `rhidp/rhdh#42` | Split on `#` |
| MR shorthand | `rhidp/rhdh!17` | Split on `!` |
| Bare MR number in a checkout | `!17` | Resolve the project from `git remote -v` |

The host is part of the identity. `rhidp/rhdh` on `gitlab.cee.redhat.com` is not
`rhidp/rhdh` anywhere else, so carry the host alongside the project path and
pass it to `glab` as `GITLAB_HOST` or as a full URL in `--repo`.

Construct the canonical URL from the resolved host, project path, and number,
using `/-/issues/` or `/-/merge_requests/` for the object type.

## Fetch the issue

```bash
gh issue view <number> --repo <owner/repo> --json number,title,body,labels,state,url,comments
```

| Field | JSON path |
|---|---|
| `summary` | `.title` |
| `description` | `.body` |
| `labels` | `.labels[].name` |
| `state` | `.state` (`OPEN` or `CLOSED`) |
| `comments` | `.comments[] | {author, body, createdAt}` |

`references/glab-cli.md` maps the same fields for a GitLab issue, where the
names and the casing differ.

## Resolve the workspace

Both `rhdh-plugins` and `community-plugins` organize code under
`workspaces/<name>/`. Apply these strategies in order and record which one
answered, because a caller that knows the strategy can judge the confidence:

1. **Label** — a label of the form `workspace/<name>` (for example
   `workspace/rbac`, `workspace/report-portal`). Take the part after the slash.
2. **Body field** — a `### Workspace` heading followed by the name. The
   community-plugins bug template emits this.
3. **Title prefix** — titles often read `plugin-<name>: description` or
   `<workspace>: description`. Take the prefix before the first colon and drop a
   leading `plugin-`.
4. **Package name** — scan the body for
   `@red-hat-developer-hub/backstage-plugin-<name>` or
   `@backstage-community/plugin-<name>` and derive the workspace from it.
5. **Unresolved** — report `null` and ask the user which workspace to target.

A Jira issue carries no workspace label. Map its Component to a workspace
directory instead; `/rhdh-plugin-bug-fix` owns that table.

## Interaction payloads

These are payloads, not authorization. This skill executes none of them. The
calling skill states the exact command, repository, issue number, and body or
label, gets approval for that stated set, and reports the outcome of every
operation afterwards. `/mutation-gate` owns that rule.

```bash
gh issue comment <number> --repo <owner/repo> --body "<exact body>"
gh issue edit <number> --repo <owner/repo> --add-label "<label>"
gh issue edit <number> --repo <owner/repo> --remove-label "<label>"
gh issue edit <number> --repo <owner/repo> --body-file "<path>"
```

An issue body is multi-line Markdown. Write it to an absolute readable file in
a unique temporary directory and pass `--body-file`, never `--body`, so the
content reaches `gh` as data rather than as shell syntax. `--body-file`
replaces the whole body — a caller that must preserve hand-written sections
reads the current body, edits it, and passes the result, rather than rendering
a fresh one from a template.

The GitLab equivalents are in `references/glab-cli.md`.

## Errors

| Scenario | Action |
|---|---|
| `gh` or `glab` not authenticated | Stop at the readiness check and report that `gh auth login`, or `glab auth login --hostname <host>`, is required |
| Issue not found (404) | Report `Issue #<n> not found in <repo>` and ask the user to confirm the number and repository |
| No write access | A label, comment, or body write fails; report it and let the caller continue the read-only work |
| Issue already closed | Report the state and ask whether to proceed |
| Repository undetectable for a bare number | Ask for the repository rather than guessing from a similarly named remote |
| A number without a sigil on GitLab | Ask whether it is an issue or a merge request rather than trying both |
