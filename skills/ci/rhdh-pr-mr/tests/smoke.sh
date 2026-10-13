#!/usr/bin/env bash
# Smoke tests for create-pr-mr.sh (no network).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SH="${ROOT}/scripts/create-pr-mr.sh"

bash -n "${SH}"
command -v shellcheck >/dev/null && shellcheck --severity=warning "${SH}"

out=$("${SH}" --help)
printf '%s\n' "${out}" | grep -q 'create-pr-mr.sh' || {
  echo "help missing usage" >&2
  exit 1
}

tmpdir=$(mktemp -d)
trap 'rm -rf "${tmpdir}"' EXIT
git init -q "${tmpdir}"
git -C "${tmpdir}" config user.email 'test@example.com'
git -C "${tmpdir}" config user.name 'test'
git -C "${tmpdir}" remote add origin 'https://github.com/example/rhdh-plugins.git'
git -C "${tmpdir}" commit --allow-empty -q -m 'init'

dry=$("${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' --dry-run)
printf '%s\n' "${dry}" | grep -q 'title=chore: test \[main\]' || {
  echo "expected title suffix [main]" >&2
  exit 1
}
printf '%s\n' "${dry}" | grep -q 'no Jira issue; skip link' || {
  echo "expected skip-link message" >&2
  exit 1
}

dry_j=$("${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --issue RHIDP-1 --dry-run)
printf '%s\n' "${dry_j}" | grep -q 'would link Jira RHIDP-1' || {
  echo "expected would-link message" >&2
  exit 1
}

echo "ok create-pr-mr smoke"
