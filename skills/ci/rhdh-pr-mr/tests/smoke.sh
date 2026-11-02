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

# Fixture parts. No test below repeats a literal attribution: edit a part and
# every case, including the commit trailer, follows.
f_tool='paseo'
f_agent='pi'
f_model='DeepSeek V4.1 Flash'
f_provider='EnMaaS'
f_level='off'
full_attribution="${f_tool} (${f_agent} + ${f_model} (${f_provider}), thinking: ${f_level})"
tool_attribution="${f_agent}"
# A commit may name less than the caller passes; only trailer presence counts.
commit_trailer="Assisted-By: ${f_tool} (${f_agent} + ${f_model})"
harness_model_dir='rits/deepseek-ai'
harness_model='DeepSeek-V4.1-Flash'
harness_trailer="Assisted-By: pi (${harness_model}, thinking: ${f_level})"

git init -q "${tmpdir}"
git -C "${tmpdir}" config user.email 'test@example.com'
git -C "${tmpdir}" config user.name 'test'
git -C "${tmpdir}" config commit.gpgsign false
git -C "${tmpdir}" remote add origin 'https://github.com/example/rhdh-plugins.git'
git -C "${tmpdir}" commit --allow-empty -q -m 'init' -m "${commit_trailer}"

run_dry() {
  "${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
    --issue RHIDP-1 --dry-run "$@"
}

# Full payload: tool + agent + model + provider + thinking level.
dry=$(run_dry --attribution "${full_attribution}")
printf '%s\n' "${dry}" | grep -q 'title=chore: test \[main\]' || {
  echo "expected title suffix [main]" >&2
  exit 1
}
printf '%s\n' "${dry}" | grep -Fq 'Related Jira: [RHIDP-1](https://redhat.atlassian.net/browse/RHIDP-1)' || {
  echo "expected Markdown Jira link" >&2
  exit 1
}
printf '%s\n' "${dry}" | grep -Fxq "Assisted-By: ${full_attribution}" || {
  echo "expected full attribution payload" >&2
  exit 1
}

# Tool only: the payload is optional past the tool name.
printf '%s\n' "$(run_dry --attribution "${tool_attribution}")" | grep -Fxq "Assisted-By: ${tool_attribution}" || {
  echo "expected bare tool attribution" >&2
  exit 1
}

# A caller may send the whole line; Generated-by is still accepted on read.
printf '%s\n' "$(run_dry --attribution "Assisted-By: ${tool_attribution}")" | grep -Fxq "Assisted-By: ${tool_attribution}" || {
  echo "expected verbatim Assisted-By trailer" >&2
  exit 1
}
printf '%s\n' "$(run_dry --assisted-by "Generated-by: ${tool_attribution}")" | grep -Fxq "Generated-by: ${tool_attribution}" || {
  echo "expected Generated-by alias to pass through verbatim" >&2
  exit 1
}
printf '%s\n' "$(run_dry --attribution "${tool_attribution}")" | grep -c 'Assisted-By:' | grep -qx 1 || {
  echo "expected exactly one Assisted-By line" >&2
  exit 1
}

# No flag: fall back to the running harness identity instead of a placeholder.
printf '%s\n' "$(PI_MODEL="${harness_model_dir}/${harness_model}" PI_REASONING_LEVEL="${f_level}" run_dry)" \
  | grep -Fxq "${harness_trailer}" || {
  echo "expected harness-derived attribution" >&2
  exit 1
}

if "${SH}" --cwd "${tmpdir}" --base main --head chore/test --title 'chore: test' \
  --attribution "${full_attribution}" --dry-run >/dev/null 2>&1; then
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
if run_dry --attribution "${full_attribution}" >/dev/null 2>&1; then
  echo "expected missing commit trailer to fail" >&2
  exit 1
fi

echo "ok create-pr-mr smoke"
