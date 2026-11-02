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
unset PI_MODEL PI_REASONING_LEVEL RHDH_ATTRIBUTION RHDH_ASSISTED_BY 2>/dev/null || true
rich_attribution='paseo (pi + DeepSeek V4.1 Flash (EnMaaS), thinking: off)'
tool_attribution='pi'
git init -q "${tmpdir}"
git -C "${tmpdir}" config user.email 'test@example.com'
git -C "${tmpdir}" config user.name 'test'
git -C "${tmpdir}" config commit.gpgsign false
git -C "${tmpdir}" remote add origin 'https://github.com/example/rhdh-plugins.git'
# Commit trailer payload never has to match what the caller passes; only its
# presence is required.
git -C "${tmpdir}" commit --allow-empty -q -m 'init' \
  -m 'Assisted-By: Codex (5.6 Sol High)'

run_dry() {
  "${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
    --issue RHIDP-1 --dry-run "$@"
}

# Full payload: tool + agent + model + provider + thinking level.
dry=$(run_dry --attribution "${rich_attribution}")
printf '%s\n' "${dry}" | grep -q 'title=chore: test \[main\]' || {
  echo "expected title suffix [main]" >&2
  exit 1
}
printf '%s\n' "${dry}" | grep -Fq 'Related Jira: [RHIDP-1](https://redhat.atlassian.net/browse/RHIDP-1)' || {
  echo "expected Markdown Jira link" >&2
  exit 1
}
printf '%s\n' "${dry}" | grep -Fxq "Generated-by: ${rich_attribution}" || {
  echo "expected full attribution payload" >&2
  exit 1
}

# Tool only: the payload is optional past the tool name.
printf '%s\n' "$(run_dry --attribution "${tool_attribution}")" | grep -Fxq "Generated-by: ${tool_attribution}" || {
  echo "expected bare tool attribution" >&2
  exit 1
}

# An already-formatted trailer is used verbatim, and the legacy flag alias and
# Assisted-By spelling still work.
printf '%s\n' "$(run_dry --assisted-by "Assisted-By: ${tool_attribution}")" | grep -Fxq "Assisted-By: ${tool_attribution}" || {
  echo "expected verbatim Assisted-By trailer" >&2
  exit 1
}
printf '%s\n' "$(run_dry --attribution "Generated-by: ${tool_attribution}")" | grep -c 'Generated-by:' | grep -qx 1 || {
  echo "expected no duplicated Generated-by prefix" >&2
  exit 1
}

# No flag: fall back to the running harness identity instead of a placeholder.
printf '%s\n' "$(PI_MODEL='rits/deepseek-ai/DeepSeek-V4.1-Flash' PI_REASONING_LEVEL=off run_dry)" \
  | grep -Fxq 'Generated-by: pi (DeepSeek-V4.1-Flash, thinking: off)' || {
  echo "expected harness-derived attribution" >&2
  exit 1
}

if "${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --attribution "${rich_attribution}" --dry-run >/dev/null 2>&1; then
  echo "expected missing Jira issue to fail" >&2
  exit 1
fi

if run_dry >/dev/null 2>&1; then
  echo "expected missing attribution to fail" >&2
  exit 1
fi

if run_dry --attribution 'pi
injected' >/dev/null 2>&1; then
  echo "expected multiline attribution to fail" >&2
  exit 1
fi

# Commit without any attribution trailer is rejected.
git -C "${tmpdir}" commit --allow-empty -q -m 'no trailer'
if run_dry --attribution "${rich_attribution}" >/dev/null 2>&1; then
  echo "expected missing commit trailer to fail" >&2
  exit 1
fi

echo "ok create-pr-mr smoke"
