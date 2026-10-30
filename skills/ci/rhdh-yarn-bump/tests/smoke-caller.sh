#!/usr/bin/env bash
# Regression tests for yarn-bump.sh metadata forwarding to create-pr-mr.sh.
#
# Each test runs yarn-bump.sh through its real CLI entry point with offline
# mocked dependencies (node/npm/curl/clone replaced by stubs that create a
# local git repo with a file change).  An opener spy records CLI args and
# verifies the actual generated commit trailer — so success fails if either
# metadata forwarding or trailer generation code is reverted.
#
# Inherited env is unset so tests are deterministic.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SH="${ROOT}/scripts/yarn-bump.sh"

# --- Resolve sibling opener for the spy to delegate dry-run validation to ---
if [[ -z "${CREATE_PR_MR:-}" ]]; then
  _ci_dir=$(cd "${ROOT}/.." && pwd)
  _opener="${_ci_dir}/rhdh-pr-mr/scripts/create-pr-mr.sh"
  [[ -f "${_opener}" ]] && CREATE_PR_MR="${_opener}"
fi
export CREATE_PR_MR
[[ -f "${CREATE_PR_MR:-}" ]] || { echo "[SKIP] sibling opener not found; set CREATE_PR_MR" >&2; exit 0; }

bash -n "${SH}"
command -v shellcheck >/dev/null && shellcheck --severity=warning "${SH}"

tmpdir=$(mktemp -d)
trap 'rm -rf "${tmpdir}"' EXIT

# --- Unset inherited metadata so tests are deterministic ---
unset JIRA_ISSUE RHDH_ASSISTED_BY 2>/dev/null || true

# --- Mock stubs: replace node/npm/curl/git-clone so yarn-bump.sh never
#     reaches the network.  The bump stub creates a file change so
#     commit_and_pr fires. ---
mock_bin="${tmpdir}/mock-bin"
mkdir -p "${mock_bin}"

# node stub: when called with bump-yarn.js, create a file change in --root
cat >"${mock_bin}/node" <<'NODESTUB'
#!/usr/bin/env bash
# If this is the bump-yarn.js call, fake a file change in --root
for arg in "$@"; do
  if [[ "${arg}" == *bump-yarn.js ]]; then
    root=""
    for ((i=1; i<=$#; i++)); do
      if [[ "${!i}" == "--root" ]]; then
        next=$((i+1)); root="${!next}"
      fi
    done
    if [[ -n "${root}" && -d "${root}" ]]; then
      echo '{"packageManager":"yarn@4.18.1"}' >"${root}/package.json"
    fi
    exit 0
  fi
done
# Fall through for other node calls
exec /usr/bin/node "$@"
NODESTUB
chmod +x "${mock_bin}/node"

# npm stub: return a fake version list
cat >"${mock_bin}/npm" <<'NPMSTUB'
#!/usr/bin/env bash
echo '["4.17.0","4.18.1"]'
NPMSTUB
chmod +x "${mock_bin}/npm"

# curl stub: no-op (fetch_yarn_bin skipped via --dry-run or returns failure)
cat >"${mock_bin}/curl" <<'CURLSTUB'
#!/usr/bin/env bash
exit 1
CURLSTUB
chmod +x "${mock_bin}/curl"

# gh stub: no open PRs
cat >"${mock_bin}/gh" <<'GHSTUB'
#!/usr/bin/env bash
echo '[]'
GHSTUB
chmod +x "${mock_bin}/gh"

# --- Opener spy: records CLI args AND checks the actual commit trailer ---
spy="${tmpdir}/spy-opener.sh"
cat >"${spy}" <<'SPY'
#!/usr/bin/env bash
# Append all args for test inspection (multiple repos call the spy)
printf '%s\n' "---CALL---" "$@" >>"${SPY_ARGS_LOG}"
# Extract --cwd value and check the actual commit trailer
cwd=""
assisted=""
for ((i=1; i<=$#; i++)); do
  if [[ "${!i}" == "--cwd" ]]; then next=$((i+1)); cwd="${!next}"; fi
  if [[ "${!i}" == "--assisted-by" ]]; then next=$((i+1)); assisted="${!next}"; fi
done
if [[ -n "${cwd}" && -d "${cwd}" ]]; then
  trailer_line="Assisted-By: ${assisted}"
  if ! git -C "${cwd}" log -1 --format=%B | git interpret-trailers --parse | grep -Fqx "${trailer_line}"; then
    echo "[SPY-FAIL] commit trailer mismatch: expected '${trailer_line}'" >&2
    echo "[SPY-FAIL] actual trailers:" >&2
    git -C "${cwd}" log -1 --format=%B | git interpret-trailers --parse >&2
    exit 1
  fi
fi
exit 0
SPY
chmod +x "${spy}"

# --- Helper: set up a bare repo that clone_repo can shallow-clone from ---
setup_clone_source() {
  local dest="$1"
  git init -q --bare "${dest}.git"
  local work="${dest}-work"
  git clone -q "${dest}.git" "${work}"
  git -C "${work}" config user.email 'test@example.com'
  git -C "${work}" config user.name 'test'
  git -C "${work}" config commit.gpgsign false
  echo '{"packageManager":"yarn@4.17.0"}' >"${work}/package.json"
  git -C "${work}" add -A
  git -C "${work}" commit -q -m 'init'
  git -C "${work}" push -q origin main 2>/dev/null || git -C "${work}" push -q origin HEAD:main
  rm -rf "${work}"
}

# --- Helper: run yarn-bump.sh in controlled environment ---
# Pass extra_flags after env vars to append CLI flags (e.g. --no-push).
# Default: no --no-push, so commit_and_pr calls CREATE_PR_MR (the spy).
run_yarn_bump() {
  local workdir="$1"; shift
  local -a extra_env=()
  while [[ $# -gt 0 && "$1" == *=* ]]; do extra_env+=("$1"); shift; done
  local -a extra_flags=("$@")
  env -i \
    PATH="${mock_bin}:/usr/bin:/bin:/usr/sbin:/sbin:$(dirname "$(command -v git)")" \
    HOME="${tmpdir}" \
    TERM="${TERM:-dumb}" \
    CREATE_PR_MR="${spy}" \
    SPY_ARGS_LOG="${workdir}/spy-args.log" \
    GIT_CONFIG_NOSYSTEM=1 \
    "${extra_env[@]}" \
    "${SH}" --to 4.18.1 --workdir "${workdir}" "${extra_flags[@]}" 2>&1
}

# -----------------------------------------------------------------------
# Test 1: CLI --issue and --assisted-by reach opener and trailer matches
# -----------------------------------------------------------------------
echo "=== Test 1: CLI args reach opener with matching trailer ==="
t1="${tmpdir}/t1"
mkdir -p "${t1}"
setup_clone_source "${t1}/rhdh-plugins"
# Override GH_REPOS/GL_REPOS: yarn-bump.sh hardcodes them, but clone_repo
# will fail for real repos. Instead we intercept clone via git config.
# Actually, clone_repo uses real git clone — we need the repo to exist.
# Approach: override github_clone_url to return our local bare repo.
# Since we can't easily override bash functions in a subprocess, we'll
# use a git insteadOf config to redirect.
git_cfg="${t1}/gitconfig"
cat >"${git_cfg}" <<GITCFG
[url "file://${t1}/rhdh-plugins.git"]
    insteadOf = https://github.com/redhat-developer/rhdh-plugins.git
    insteadOf = https://github.com/redhat-developer/rhdh.git
    insteadOf = https://github.com/redhat-developer/rhdh-plugin-export-overlays.git
    insteadOf = https://github.com/redhat-developer/rhdh-cli.git
[url "file://${t1}/rhdh-plugins.git"]
    insteadOf = https://gitlab.cee.redhat.com/rhidp/rhdh.git
    insteadOf = https://gitlab.cee.redhat.com/rhidp/rhdh-plugin-catalog.git
[user]
    name = test
    email = test@example.com
[commit]
    gpgsign = false
GITCFG

out1=$(run_yarn_bump "${t1}" \
  GIT_CONFIG_GLOBAL="${git_cfg}" \
  JIRA_ISSUE=RHIDP-42 \
  RHDH_ASSISTED_BY='TestTool (test-model)' \
  PRIVATE_TOKEN='' \
  GITHUB_TOKEN='' \
  GH_TOKEN='' || true)

# Spy must have fired (no --no-push) and recorded --issue and --assisted-by
[[ -f "${t1}/spy-args.log" ]] || { echo "FAIL: spy not called — opener never reached" >&2; echo "${out1}" >&2; exit 1; }
grep -Fqx 'RHIDP-42' "${t1}/spy-args.log" || { echo "FAIL: --issue RHIDP-42 not in spy args" >&2; cat "${t1}/spy-args.log" >&2; exit 1; }
grep -Fqx 'TestTool (test-model)' "${t1}/spy-args.log" || { echo "FAIL: --assisted-by not in spy args" >&2; cat "${t1}/spy-args.log" >&2; exit 1; }
# Spy verified the commit trailer matches (exits non-zero on mismatch, caught as WARN)
if printf '%s\n' "${out1}" | grep -q 'SPY-FAIL'; then
  echo "FAIL: spy detected commit trailer mismatch" >&2; printf '%s\n' "${out1}" | grep 'SPY-FAIL' >&2; exit 1
fi
echo "PASS"

# -----------------------------------------------------------------------
# Test 2: Env passthrough — JIRA_ISSUE and default RHDH_ASSISTED_BY
# -----------------------------------------------------------------------
echo "=== Test 2: env passthrough with default tool attribution ==="
t2="${tmpdir}/t2"
mkdir -p "${t2}"
setup_clone_source "${t2}/rhdh-plugins"
git_cfg2="${t2}/gitconfig"
sed "s|${t1}|${t2}|g" "${git_cfg}" >"${git_cfg2}"

out2=$(run_yarn_bump "${t2}" \
  GIT_CONFIG_GLOBAL="${git_cfg2}" \
  JIRA_ISSUE=RHIDP-99 \
  PRIVATE_TOKEN='' \
  GITHUB_TOKEN='' \
  GH_TOKEN='' || true)

# Spy must have fired and verified default tool attribution trailer
[[ -f "${t2}/spy-args.log" ]] || { echo "FAIL: spy not called" >&2; echo "${out2}" >&2; exit 1; }
grep -Fqx 'yarn-bump.sh (rhdh-yarn-bump)' "${t2}/spy-args.log" || { echo "FAIL: default attribution not forwarded" >&2; cat "${t2}/spy-args.log" >&2; exit 1; }
grep -Fqx 'RHIDP-99' "${t2}/spy-args.log" || { echo "FAIL: JIRA_ISSUE not forwarded" >&2; cat "${t2}/spy-args.log" >&2; exit 1; }
if printf '%s\n' "${out2}" | grep -q 'SPY-FAIL'; then
  echo "FAIL: spy detected trailer mismatch" >&2; printf '%s\n' "${out2}" | grep 'SPY-FAIL' >&2; exit 1
fi
echo "PASS"

# -----------------------------------------------------------------------
# Test 3: Missing JIRA_ISSUE rejected before any mutation
# -----------------------------------------------------------------------
echo "=== Test 3: missing JIRA_ISSUE rejected before clone ==="
t3="${tmpdir}/t3"
mkdir -p "${t3}"
out3=$(run_yarn_bump "${t3}" \
  JIRA_ISSUE='' \
  PRIVATE_TOKEN='' \
  GITHUB_TOKEN='' \
  GH_TOKEN='' \
  --no-push 2>&1 || true)
# Must NOT have cloned anything
if [[ -d "${t3}/rhdh-plugins" ]]; then
  echo "FAIL: clone happened despite missing JIRA_ISSUE" >&2; exit 1
fi
if printf '%s\n' "${out3}" | grep -q 'JIRA_ISSUE.*required'; then
  echo "PASS"
else
  echo "FAIL: expected JIRA_ISSUE rejection message" >&2; printf '%s\n' "${out3}" >&2; exit 1
fi

# -----------------------------------------------------------------------
# Test 4: Invalid JIRA_ISSUE format rejected before clone
# -----------------------------------------------------------------------
echo "=== Test 4: invalid JIRA_ISSUE rejected ==="
t4="${tmpdir}/t4"
mkdir -p "${t4}"
out4=$(run_yarn_bump "${t4}" \
  JIRA_ISSUE='not-a-key' \
  PRIVATE_TOKEN='' \
  GITHUB_TOKEN='' \
  GH_TOKEN='' \
  --no-push 2>&1 || true)
if [[ -d "${t4}/rhdh-plugins" ]]; then
  echo "FAIL: clone happened despite invalid JIRA_ISSUE" >&2; exit 1
fi
if printf '%s\n' "${out4}" | grep -q 'JIRA_ISSUE.*required'; then
  echo "PASS"
else
  echo "FAIL: expected JIRA_ISSUE rejection" >&2; printf '%s\n' "${out4}" >&2; exit 1
fi

# -----------------------------------------------------------------------
# Test 5: Multiline attribution rejected before clone
# -----------------------------------------------------------------------
echo "=== Test 5: multiline attribution rejected ==="
t5="${tmpdir}/t5"
mkdir -p "${t5}"
multiline=$'line1\nline2'
out5=$(run_yarn_bump "${t5}" \
  JIRA_ISSUE='RHIDP-1' \
  RHDH_ASSISTED_BY="${multiline}" \
  PRIVATE_TOKEN='' \
  GITHUB_TOKEN='' \
  GH_TOKEN='' \
  --no-push 2>&1 || true)
if [[ -d "${t5}/rhdh-plugins" ]]; then
  echo "FAIL: clone happened despite multiline attribution" >&2; exit 1
fi
if printf '%s\n' "${out5}" | grep -q 'single non-blank line'; then
  echo "PASS"
else
  echo "FAIL: expected single-line rejection" >&2; printf '%s\n' "${out5}" >&2; exit 1
fi

# -----------------------------------------------------------------------
# Test 6: Whitespace-only attribution rejected before clone
# -----------------------------------------------------------------------
echo "=== Test 6: whitespace-only attribution rejected ==="
t6="${tmpdir}/t6"
mkdir -p "${t6}"
out6=$(run_yarn_bump "${t6}" \
  JIRA_ISSUE='RHIDP-1' \
  RHDH_ASSISTED_BY='   ' \
  PRIVATE_TOKEN='' \
  GITHUB_TOKEN='' \
  GH_TOKEN='' \
  --no-push 2>&1 || true)
if [[ -d "${t6}/rhdh-plugins" ]]; then
  echo "FAIL: clone happened despite whitespace-only attribution" >&2; exit 1
fi
if printf '%s\n' "${out6}" | grep -q 'single non-blank line'; then
  echo "PASS"
else
  echo "FAIL: expected single-line rejection" >&2; printf '%s\n' "${out6}" >&2; exit 1
fi

# -----------------------------------------------------------------------
# Test 7: CLI --issue overrides env JIRA_ISSUE
# -----------------------------------------------------------------------
echo "=== Test 7: CLI --issue overrides env ==="
t7="${tmpdir}/t7"
mkdir -p "${t7}"
setup_clone_source "${t7}/rhdh-plugins"
git_cfg7="${t7}/gitconfig"
sed "s|${t1}|${t7}|g" "${git_cfg}" >"${git_cfg7}"

out7=$(env -i \
  PATH="${mock_bin}:/usr/bin:/bin:/usr/sbin:/sbin:$(dirname "$(command -v git)")" \
  HOME="${tmpdir}" TERM="${TERM:-dumb}" \
  CREATE_PR_MR="${spy}" SPY_ARGS_LOG="${t7}/spy-args.log" \
  GIT_CONFIG_GLOBAL="${git_cfg7}" GIT_CONFIG_NOSYSTEM=1 \
  JIRA_ISSUE=RHIDP-WRONG \
  PRIVATE_TOKEN='' GITHUB_TOKEN='' GH_TOKEN='' \
  "${SH}" --to 4.18.1 --workdir "${t7}" \
  --issue RHIDP-77 --assisted-by 'OverrideTool' 2>&1 || true)

# Spy must have recorded the CLI-overridden values, not env values
[[ -f "${t7}/spy-args.log" ]] || { echo "FAIL: spy not called" >&2; echo "${out7}" >&2; exit 1; }
grep -Fqx 'RHIDP-77' "${t7}/spy-args.log" || { echo "FAIL: CLI --issue not forwarded" >&2; cat "${t7}/spy-args.log" >&2; exit 1; }
grep -Fqx 'OverrideTool' "${t7}/spy-args.log" || { echo "FAIL: CLI --assisted-by not forwarded" >&2; cat "${t7}/spy-args.log" >&2; exit 1; }
if printf '%s\n' "${out7}" | grep -q 'SPY-FAIL'; then
  echo "FAIL: spy detected trailer mismatch" >&2; printf '%s\n' "${out7}" | grep 'SPY-FAIL' >&2; exit 1
fi
echo "PASS"

echo "ok yarn-bump caller smoke"
