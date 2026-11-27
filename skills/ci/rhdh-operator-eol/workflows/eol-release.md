# EOL an rhdh-operator release branch

Given a `release-*` branch (or the `x.y.0` tag that just shipped), edit
`redhat-developer/rhdh-operator` on `main` and open a pull request as the
signed-in user.

## 1. Resolve the checkout and preflight

Invoke `/rhdh-context` and read the `rhdh-operator` path it reports. Stop and
tell the user to run `/setup-rhdh-skills` when that path is missing.

```bash
REPO=<rhdh-operator path from /rhdh-context>
test -x "${REPO}/hack/eol-release.sh"
git -C "${REPO}" rev-parse --show-toplevel
git -C "${REPO}" remote get-url origin
```

Stop when `hack/eol-release.sh` is absent, the working tree is not
`rhdh-operator`, or `origin` contains `x-access-token`. Push must use the
user's SSH remote or a user credential that can edit workflow files. Do not
rewrite `origin` to an App token URL or `RHDH_BOT_TOKEN`.

Python 3.9+ and `git` are required before local edits. `gh` is required before
proposing publication.

Accept either input and normalize it:

| User said | Wrapper flag |
|---|---|
| `release-1.9` or `1.9` | `--branch release-1.9` |
| `2.1.0` | `--tag 2.1.0` |

Pass `--issue` to `/rhdh-pr-mr` only when the conversation already has a Jira
key such as `RHIDP-9776`. Do not invent one.

## 2. Inspect without changing the checkout

```bash
SKILL_DIR=/absolute/path/to/installed/rhdh-operator-eol
python3 "${SKILL_DIR}/scripts/eol_operator.py" \
  --root "${REPO}" --branch release-1.9 --json
```

Use `--tag 2.1.0` instead of `--branch` when the user named a release tag.
The wrapper prints one JSON object on stdout and the `hack/eol-release.sh`
log on stderr. Consume the whole JSON object. It names `tag`, `eol_branch`,
`changed`, and `files`. Dry-run performs no fetch, branch, write, commit,
push, or pull-request operation.

Stop when `changed` is false: the matrices already omit that branch.

## 3. Prepare a local review branch and apply the edits

```bash
test -z "$(git -C "${REPO}" status --porcelain --untracked-files=all)"
git -C "${REPO}" fetch origin main
git -C "${REPO}" switch -c "chore/eol-${eol_branch}" origin/main
python3 "${SKILL_DIR}/scripts/eol_operator.py" \
  --root "${REPO}" --tag "${tag}" --write --json
git -C "${REPO}" diff --check
git -C "${REPO}" diff -- \
  .github/workflows/nightly.yaml \
  .github/workflows/nightly-upgrade-test.yaml \
  .github/renovate.json
```

`--write` edits only those files. It never stages, commits, fetches, pushes,
or calls `gh`. Show the JSON and the diff before any publication plan.
Leave `nightly-postgresql-upgrade-test.yaml` to `hack/eol-release.sh`; that
script skips it when the matrix would become empty.

The user's request to EOL this branch authorizes the local review branch and
those named file edits after the dry run. Do not invoke `/mutation-gate` for
those local operations.

## 4. Build the fixed pull-request payload

Read `references/pr-body.md` and replace `{tag}`, `{eol_branch}`, and
`{attribution}`. Write the tool that actually ran, for example
`paseo (pi + DeepSeek V4.1 Flash (EnMaaS), thinking: off)`, dropping every part you cannot
confirm. Keep the headings. Do not invoke a prose editor.

Title:

```text
chore(ci): end of life {eol_branch} after {tag}
```

`/rhdh-pr-mr` appends ` [main]` when that suffix is missing. Write the filled
body to a unique temporary file.

Resolve attribution from what is known and stop there, the same grammar
`/rhdh-pr-mr` documents. Put an `Assisted-By:` trailer with that payload on
the commit.

## 5. Gate commit, push, and pull request

Invoke `/mutation-gate` once with two ordered operations:

| Operation | Target and exact command | Preview and verification | Failure behavior |
|---|---|---|---|
| Commit | The paths in the JSON `files` list; exact `git add -- <paths>` and `git commit` with the title as the subject and the `Assisted-By:` trailer | Show the diff and subject; verify `git show --stat --oneline HEAD` | Stop before `/rhdh-pr-mr` |
| Push and open | Invoke `/rhdh-pr-mr` with `--cwd "${REPO}" --base main --head chore/eol-${eol_branch} --title 'chore(ci): end of life ${eol_branch} after ${tag}' --body-file <temp> --attribution '<resolved>'` and `--issue` only when a key is already known | Show remote URL, branch, commit SHA, title, and filled body; report the `url:` line | Report the local commit and leave the pull request uncreated |

Wait for approval of that exact set. If the diff, branch, title, or body
changes, render and approve a new set. Execute in order and report every
outcome, including skipped operations.

Do not pass `--label lgtm` or `--label approved`. This pull request edits
workflow YAML and needs a human review.

## 6. Report

Report the tag, EOL branch, changed paths, local commit SHA, pull-request URL,
and the outcome of every gated operation. When approval was withheld, state
that nothing was pushed and no pull request was opened. The EOL branch in
the operator repository is not deleted by this skill.
