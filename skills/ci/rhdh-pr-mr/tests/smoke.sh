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
model_attribution='Codex (5.6 Sol High)'
tool_attribution='Codex'
unknown_attribution='Unknown AI (possibly Skynet)'
git init -q "${tmpdir}"
git -C "${tmpdir}" config user.email 'test@example.com'
git -C "${tmpdir}" config user.name 'test'
git -C "${tmpdir}" config commit.gpgsign false
git -C "${tmpdir}" remote add origin 'https://github.com/example/rhdh-plugins.git'
git -C "${tmpdir}" commit --allow-empty -q -m 'init' \
  -m "Assisted-By: ${model_attribution}"

dry=$("${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --issue RHIDP-1 --assisted-by "${model_attribution}" --dry-run)
printf '%s\n' "${dry}" | grep -q 'title=chore: test \[main\]' || {
  echo "expected title suffix [main]" >&2
  exit 1
}
printf '%s\n' "${dry}" | grep -Fq 'Related Jira: [RHIDP-1](https://redhat.atlassian.net/browse/RHIDP-1)' || {
  echo "expected Markdown Jira link" >&2
  exit 1
}
printf '%s\n' "${dry}" | grep -Fq "Assisted-By: ${model_attribution}" || {
  echo "expected model-specific attribution" >&2
  exit 1
}

git -C "${tmpdir}" commit --allow-empty -q -m 'tool-only attribution' \
  -m "Assisted-By: ${tool_attribution}"
dry_tool=$("${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --issue RHIDP-1 --assisted-by "${tool_attribution}" --dry-run)
printf '%s\n' "${dry_tool}" | grep -Fq "Assisted-By: ${tool_attribution}" || {
  echo "expected tool-only attribution" >&2
  exit 1
}

git -C "${tmpdir}" commit --allow-empty -q -m 'unknown attribution' \
  -m "Assisted-By: ${unknown_attribution}"
dry_unknown=$("${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --issue RHIDP-1 --assisted-by "${unknown_attribution}" --dry-run)
printf '%s\n' "${dry_unknown}" | grep -Fq "Assisted-By: ${unknown_attribution}" || {
  echo "expected unknown-AI attribution" >&2
  exit 1
}

if "${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --assisted-by "${model_attribution}" --dry-run >/dev/null 2>&1; then
  echo "expected missing Jira issue to fail" >&2
  exit 1
fi

if "${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --issue RHIDP-1 --dry-run >/dev/null 2>&1; then
  echo "expected missing attribution to fail" >&2
  exit 1
fi

if "${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --issue RHIDP-1 --assisted-by "${model_attribution} (mismatch)" --dry-run >/dev/null 2>&1; then
  echo "expected mismatched commit attribution to fail" >&2
  exit 1
fi

echo "ok create-pr-mr smoke"
