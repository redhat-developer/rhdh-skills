#!/usr/bin/env bash
# Smoke tests for yarn-bump.sh's caller half: the attribution trailer it commits
# and the metadata it forwards to create-pr-mr.sh. No clone, npm, or curl.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SH="${ROOT}/scripts/yarn-bump.sh"

bash -n "${SH}"
command -v shellcheck >/dev/null && shellcheck --severity=warning "${SH}"

work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

# Stands in for create-pr-mr.sh and records exactly what it was called with.
recorder="${work}/create-pr-mr"
cat >"${recorder}" <<'REC'
#!/usr/bin/env bash
printf '%s\n' "$@" >>"${RECORDER_LOG:?}"
REC
chmod +x "${recorder}"

attribution="rhdh-yarn-bump (pi + DeepSeek V4.1 Flash, thinking: off)"

# run_case <label> <RHDH_ATTRIBUTION|""> <expected trailer line> <expected forwarded value>
run_case() {
  local label="$1" attr="$2" expected="$3" forwarded="$4"
  local repo="${work}/repo-${label}" log="${work}/log-${label}"
  : >"${log}"
  git init -q "${repo}"
  git -C "${repo}" config user.email 'bot@example.com'
  git -C "${repo}" config user.name 'bot'
  git -C "${repo}" config commit.gpgsign false
  printf 'x\n' >"${repo}/file.txt"
  (
    # Attribution and issue are read when the script is sourced, so set the env
    # first; the remaining globals are reset by that source, so set them after.
    export RECORDER_LOG="${log}" CREATE_PR_MR="${recorder}" JIRA_ISSUE=RHIDP-1234
    if [[ -n "${attr}" ]]; then
      export RHDH_ATTRIBUTION="${attr}"
    else
      unset RHDH_ATTRIBUTION RHDH_ASSISTED_BY
    fi
    # shellcheck source=/dev/null
    source "${SH}"
    export TO=4.18.1 BRANCH=main TOPIC=chore/automated-yarn-bump DRY_RUN=0 PUSH=1
    commit_and_pr "${repo}" 'example/repo'
  )
  git -C "${repo}" log -1 --format=%B | git interpret-trailers --parse \
    | grep -Fxq "${expected}" || {
    echo "${label}: commit trailer is not '${expected}'" >&2
    exit 1
  }
  grep -Fxq -- '--issue' "${log}" && grep -Fxq 'RHIDP-1234' "${log}" || {
    echo "${label}: --issue RHIDP-1234 not forwarded" >&2
    exit 1
  }
  grep -Fxq -- '--attribution' "${log}" && grep -Fxq -- "${forwarded}" "${log}" || {
    echo "${label}: --attribution '${forwarded}' not forwarded" >&2
    exit 1
  }
}

run_case 'full' "${attribution}" "Assisted-By: ${attribution}" "${attribution}"
# No env: the scheduled bump names the script and claims no model.
run_case 'default' '' 'Assisted-By: rhdh-yarn-bump' 'rhdh-yarn-bump'
# A value that already carries a trailer key is kept verbatim, never re-prefixed.
run_case 'verbatim' 'Generated-by: ci-runner' 'Generated-by: ci-runner' 'Generated-by: ci-runner'

# Preflight rejects metadata the opener would reject anyway, before any clone.
if TO=4.18.1 JIRA_ISSUE=RHIDP-1234 "${SH}" --workdir "${work}/wd" --attribution '   ' >/dev/null 2>&1; then
  echo 'expected blank attribution to fail' >&2
  exit 1
fi
if TO=4.18.1 "${SH}" --workdir "${work}/wd" >/dev/null 2>&1; then
  echo 'expected missing Jira issue to fail' >&2
  exit 1
fi

echo 'ok yarn-bump caller smoke'
