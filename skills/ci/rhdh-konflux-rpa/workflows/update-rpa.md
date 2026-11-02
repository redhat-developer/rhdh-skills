# Update RHDH release-data RPA tags

Given `MAJOR.MINOR.PATCH`, update the matching stream's four
ReleasePlanAdmission files in a user-provided `konflux-release-data` checkout.

## 1. Resolve the checkout and preflight

Never assume a checkout path. Accept the repository root or its
`config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhdh/` directory.
Resolve the owning repository with `git rev-parse --show-toplevel`.

Before local branch or file mutation, require Git 2.x, Python 3.9+, and the
canonical repository identity. Run these checks without printing credentials:

```bash
git --version
python3 --version
git -C "${REPO}" remote get-url origin
```

Stop before creating a branch when the required runtime is unavailable or
`origin` is not exactly the canonical `releng/konflux-release-data` repository.
Before proposing publication, also run `glab --version` and
`glab auth status --hostname gitlab.cee.redhat.com`. `tox` is optional and needed
only when the user requests repository schema validation.

## 2. Inspect without changing the checkout

Run the bundled script in dry-run mode first. This command performs no fetch,
checkout, branch, file, commit, push, browser, or merge-request operation:

```bash
SKILL_DIR=/absolute/path/to/installed/rhdh-konflux-rpa
SCRIPT="${SKILL_DIR}/scripts/update_rpa_tags.py"
python3 "${SCRIPT}" 1.9.7 --repo-dir "${REPO}" --dry-run
```

Confirm the stream and replacement counts. The script must select exactly:

- `rhdh-MAJOR-MINOR-prod.yaml`
- `rhdh-MAJOR-MINOR-stage.yaml`
- `rhdh-plugin-catalog-MAJOR-MINOR-prod.yaml`
- `rhdh-plugin-catalog-MAJOR-MINOR-stage.yaml`

It preserves stream tags such as `1.9` and plugin suffixes such as `--1.20.2`.
It rejects a symlinked canonical directory, symlinked or non-regular target
files, physical targets outside that directory, and multiline flow-style
`tags` values before writing. A local update stages all four replacements in
their target directory and restores the original bytes and modes if a replace
fails; it must never report a partial update as successful.

## 3. Prepare a local review branch and diff

Require a clean checkout. Create a new local branch from the user's chosen base,
then run the script in local-only mode:

```bash
test -z "$(git -C "${REPO}" status --porcelain --untracked-files=all)"
git -C "${REPO}" fetch origin main
git -C "${REPO}" switch -c "chore/rhdh-update-rpa-1.9.7" "origin/main"
python3 "${SCRIPT}" 1.9.7 --repo-dir "${REPO}" --local-only
git -C "${REPO}" diff --check
git -C "${REPO}" diff -- \
  config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhdh/rhdh-1-9-prod.yaml \
  config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhdh/rhdh-1-9-stage.yaml \
  config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhdh/rhdh-plugin-catalog-1-9-prod.yaml \
  config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhdh/rhdh-plugin-catalog-1-9-stage.yaml
```

`--local-only` edits only those files. It never stages, commits, fetches, pushes,
calls `glab`, or opens a browser. If validation is requested, add `--validate` or
run `tox -e test` after the edit. Show the diff and validation result before any
publication plan.

The user's request to update these tags authorizes the local review branch and
the four named file edits after the dry run. Do not invoke `/mutation-gate` for
those local operations. Commit, push, and merge-request creation remain gated.

## 4. Build the fixed merge-request payload

Read `references/mr-body.md` and replace `{new_version}`, `{stream}`,
`{old_versions}`, and `{attribution}`. Write the tool that actually ran, e.g.
`paseo (pi + DeepSeek V4.1 Flash (EnMaaS), thinking: off)`, dropping every part
you cannot confirm — never a literal from this template. Keep the headings and
the empty Tickets section. The repository's static prose linter checks this
fixed template in flavored mode; do not invoke a prose editor at runtime.

Use this title:

```text
chore: update rhdh-MAJOR-MINOR-*.yaml RPAs for upcoming release MAJOR.MINOR.PATCH
```

Write the filled body to a unique temporary file for the preview and command.
Invoke `/rhdh-forge` with the GitLab host, `releng/konflux-release-data`, exact
base and head branches, title, and body file. It returns the exact merge-request
command and payload without executing them. Use that returned command unchanged
in the write plan.

## 5. Gate commit, push, and merge request

Invoke `/mutation-gate` once with three ordered operations:

| Operation | Target and exact command | Preview and verification | Failure behavior |
|---|---|---|---|
| Commit | The four named RPA paths; exact `git add -- <paths>` and `git commit -s -m <subject>` commands | Show the diff and commit subject; verify `git show --stat --oneline HEAD` | Stop before push |
| Push | `origin`, exact branch, and `git push -u origin <branch>` | Show remote URL, branch, and commit SHA; verify with `git ls-remote origin refs/heads/<branch>` | Stop before MR |
| Merge request | `releng/konflux-release-data`, exact command returned by `/rhdh-forge` | Show target branch, title, and the filled body from the temporary file; parse the returned URL with Python 3 and verify `changes_count` is nonzero | Report the pushed branch and leave MR uncreated |

Wait for approval of that exact set. If the diff, branch, target, title, or body
changes, render and approve a new set. Execute in order and report every outcome,
including skipped operations.

## 6. Report

Report old and new versions, four file paths, replacement count, validation,
local commit SHA, pushed branch, merge-request URL, and the outcome of every
gated operation. When approval was withheld, state that nothing was pushed and
no merge request was opened.
