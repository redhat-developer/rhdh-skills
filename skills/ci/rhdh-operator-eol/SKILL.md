---
name: rhdh-operator-eol
description: >-
  Marks a Red Hat Developer Hub operator release branch end-of-life in
  redhat-developer/rhdh-operator: runs hack/eol-release.sh, removes the
  branch from nightly.yaml and nightly-upgrade-test.yaml, appends a Renovate
  enabled:false rule, and opens a pull request against main. Use for
  "EOL release-1.9", "end of life the operator branch after 2.1.0",
  "RHIDP-9776", "hack/eol-release.sh", or dropping a release-* line from
  the operator nightly matrix. Operator nightly and upgrade matrices only.
compatibility: "A local rhdh-operator checkout that contains hack/eol-release.sh; Python 3.9+; git; gh authenticated as the user who will push workflow YAML."
---

# RHDH operator release-branch EOL

Drop one `release-*` branch from `redhat-developer/rhdh-operator` nightly CI
and Renovate by running that repository's `hack/eol-release.sh`, then opening
a pull request as the signed-in user. GitHub allows that identity to edit
`.github/workflows`. A GitHub App or bot PAT without the Workflows permission
cannot, which is why `.github/workflows/eol-release.yaml` failed on the 2.1.0
dispatch.

This skill does not fire on a tag push. A maintainer invokes it with the EOL
branch (`release-1.9`) or the release tag that just shipped (`2.1.0`).

## Route

Load `workflows/eol-release.md` and follow it end to end. Execute the bundled
`scripts/eol_operator.py` by path relative to this installed skill. That wrapper
resolves `--branch` to a release tag and runs `hack/eol-release.sh`; it never
commits, pushes, or opens a pull request.

## Boundaries

- `/rhdh-prow-release-branch` owns Prow jobs for `redhat-developer/rhdh`.
- `/rhdh-platform-lifecycle` owns vendor support dates.
- `/rhdh-context` locates the `rhdh-operator` checkout.
- `/rhdh-pr-mr` pushes the topic branch and opens the pull request.
- Do not re-run or repair `.github/workflows/eol-release.yaml`. Do not mint a
  GitHub App token, and do not set `GH_TOKEN` or `GITHUB_TOKEN` to
  `RHDH_BOT_TOKEN` or an App installation token. Do not add `lgtm` or `approved`.

## Write boundary

Dry-run, the local review branch, and `--write` file edits stay in the user's
checkout and need no write gate. The user's request to EOL a named branch
authorizes those local edits, not publication.

Follow `/mutation-gate` for commit and for `/rhdh-pr-mr` (push plus open). Treat
them as one ordered publication set. The pull request body is the filled
`references/pr-body.md` template; do not invoke a prose editor.

## Completion

Name the release tag, the EOL branch, every path `hack/eol-release.sh` updated
(or that nothing changed), the local branch and commit, the pull-request URL
from `/rhdh-pr-mr`, and the outcome or skipped state of every gated operation.
Report explicitly when nothing was pushed. The branch itself is not deleted.
