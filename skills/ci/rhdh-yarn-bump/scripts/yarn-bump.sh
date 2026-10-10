#!/usr/bin/env bash
# Multi-repo Yarn Berry 4.x bump. Mutator: bump-yarn.js.
# Opens PRs/MRs via sibling skills/ci/rhdh-pr-mr (no Jira key for bot bumps).
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
BUMP_JS="${SCRIPT_DIR}/bump-yarn.js"
: "${CREATE_PR_MR:=${SCRIPT_DIR}/../../rhdh-pr-mr/scripts/create-pr-mr.sh}"
TOPIC="chore/automated-yarn-bump"
BOT_NAME="rhdh-bot service account"
BOT_EMAIL="rhdh-bot@redhat.com"

BRANCH="main"
TO=""
DRY_RUN=0
PUSH=1
WORKDIR=""
RC=0
GH_BIN_ROOT=""
YARN_BIN=""

GH_REPOS=(
  redhat-developer/rhdh-plugins
  redhat-developer/rhdh
  redhat-developer/rhdh-plugin-export-overlays
  redhat-developer/rhdh-cli
)
GL_REPOS=(
  rhidp/rhdh
  rhidp/rhdh-plugin-catalog
)

usage() {
  cat <<'EOF'
Usage:
  yarn-bump.sh [--to VER] [--branch main] [--dry-run] [--no-push] [--workdir DIR]

Resolves latest Yarn 4.x when --to is omitted. Clones GitHub then GitLab CEE,
runs bump-yarn.js --from-all. Downloads the Yarn CLI once and passes --bin so
each PR/MR commits yarn-<to>.cjs. If that download fails, GitLab falls back to
copying the binary from a GitHub bump. Commits as rhdh-bot and opens PRs/MRs on
chore/automated-yarn-bump via rhdh-pr-mr (no Jira).

Env: GITHUB_TOKEN or GH_TOKEN; PRIVATE_TOKEN (GitLab CEE); CREATE_PR_MR (optional).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --to) TO="${2:?}"; shift 2 ;;
    --branch) BRANCH="${2:?}"; shift 2 ;;
    --workdir) WORKDIR="${2:?}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --no-push) PUSH=0; shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

for bin in node npm jq git curl; do
  command -v "$bin" >/dev/null || { echo "[ERROR] need ${bin}" >&2; exit 1; }
done
[[ -f "${BUMP_JS}" ]] || { echo "[ERROR] missing ${BUMP_JS}" >&2; exit 1; }
[[ -f "${CREATE_PR_MR}" ]] || { echo "[ERROR] missing ${CREATE_PR_MR} (rhdh-pr-mr skill)" >&2; exit 1; }

if [[ -z "${TO}" ]]; then
  TO=$(npm view @yarnpkg/cli versions --json \
    | jq -r '[.[] | select(test("^4\\.[0-9]+\\.[0-9]+$"))] | last')
  [[ -n "${TO}" && "${TO}" != "null" ]] || { echo "[ERROR] no Yarn 4.x on npm" >&2; exit 1; }
fi
echo "[INFO] yarn bump to=${TO} branch=${BRANCH}"

fetch_yarn_bin() {
  local dest="${WORKDIR}/yarn-${TO}.cjs"
  local url="https://repo.yarnpkg.com/${TO}/packages/yarnpkg-cli/bin/yarn.js"
  if [[ ! "${TO}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "[ERROR] refusing to fetch Yarn version ${TO}" >&2
    exit 1
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[INFO] dry-run: would curl -fsSL ${url}"
    return 0
  fi
  if curl -fsSL --retry 3 -o "${dest}" "${url}" \
    && [[ "$(head -c 19 "${dest}")" == "#!/usr/bin/env node" ]]; then
    chmod +x "${dest}"
    YARN_BIN="${dest}"
    echo "[INFO] fetched ${url}"
    return 0
  fi
  rm -f "${dest}"
  echo "[WARN] Yarn CLI download failed; GitHub still runs yarn set version, GitLab copies a GitHub binary when one exists" >&2
  YARN_BIN=""
}

if [[ -z "${WORKDIR}" ]]; then
  WORKDIR=$(mktemp -d)
  trap 'rm -rf "${WORKDIR}"' EXIT
fi
mkdir -p "${WORKDIR}"
fetch_yarn_bin

bump_args() {
  local dest="$1"
  local -n _args="$2"
  _args=(--to "${TO}" --from-all --root "${dest}")
  if [[ -n "${YARN_BIN}" && -f "${YARN_BIN}" ]]; then
    _args+=(--bin "${YARN_BIN}")
  fi
}

github_clone_url() {
  local slug="$1"
  local tok="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
  if [[ -n "${tok}" ]]; then
    printf 'https://x-access-token:%s@github.com/%s.git' "${tok}" "${slug}"
  else
    printf 'https://github.com/%s.git' "${slug}"
  fi
}

clone_repo() {
  local url="$1" dest="$2"
  git clone --branch "${BRANCH}" --single-branch --depth 50 "${url}" "${dest}"
  git -C "${dest}" config user.name "${BOT_NAME}"
  git -C "${dest}" config user.email "${BOT_EMAIL}"
}

has_open_gh_pr() {
  local dir="$1"
  command -v gh >/dev/null || return 1
  gh pr list --repo "$(git -C "${dir}" remote get-url origin | sed -E 's#.*github.com[:/](.+)(\.git)?$#\1#')" \
    --base "${BRANCH}" --state open --author rhdh-bot \
    --json headRefName,url 2>/dev/null \
    | jq -e --arg p "${TOPIC}" '[.[] | select(.headRefName | startswith($p))] | length > 0' >/dev/null
}

has_open_gl_mr() {
  local slug="$1"
  local tok="${PRIVATE_TOKEN:-}"
  local host="${CI_SERVER_HOST:-gitlab.cee.redhat.com}"
  [[ -n "${tok}" ]] || return 1
  local enc
  enc=$(printf '%s' "${slug}" | jq -sRr @uri)
  curl -fsS --header "PRIVATE-TOKEN: ${tok}" \
    "https://${host}/api/v4/projects/${enc}/merge_requests?state=opened&target_branch=${BRANCH}" \
    | jq -e --arg p "${TOPIC}" '[.[] | select(.source_branch | startswith($p))] | length > 0' >/dev/null
}

# Yarn rewrites .yarnrc.yml with double quotes; repos that run prettier:check
# (rhdh-cli) reject that. Format changed files before the commit when the
# repo defines a prettier script. Missing node_modules is a hard failure so
# we do not open a PR CI will reject.
apply_repo_formatters() {
  [[ -f package.json ]] || return 0
  jq -e '.scripts["prettier:check"] or .scripts["prettier:fix"]' package.json >/dev/null 2>&1 || return 0
  local changed=()
  local f
  while IFS= read -r f; do
    [[ -n "${f}" ]] && changed+=("${f}")
  done < <(git diff --name-only --diff-filter=ACMR)
  [[ ${#changed[@]} -gt 0 ]] || return 0
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[INFO] dry-run: would prettier --write ${#changed[@]} changed files"
    return 0
  fi
  echo "[INFO] prettier --write (${#changed[@]} files)"
  yarn prettier --ignore-unknown --write -- "${changed[@]}"
}

commit_and_pr() {
  local dir="$1" slug="$2"
  local title="chore(deps): bump Yarn to ${TO}"
  local body body_file
  pushd "${dir}" >/dev/null
  if [[ -z "$(git status --porcelain)" ]]; then
    echo "[INFO] ${slug}: no diff"
    popd >/dev/null
    return 0
  fi
  apply_repo_formatters
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[INFO] dry-run: would commit/PR ${slug}"
    popd >/dev/null
    return 0
  fi
  git add -A
  git commit -s -m "$(printf 'chore(deps): bump Yarn to %s\n\nOpened by yarn-bump.sh (rhdh-yarn-bump skill).\n' "${TO}")"
  if [[ "${PUSH}" -eq 0 ]]; then
    echo "[INFO] ${slug}: committed, --no-push"
    popd >/dev/null
    return 0
  fi
  body_file=$(mktemp)
  body="$(printf '## Summary\n- Bump Yarn Berry to `%s`.\n\n## Test plan\n- [ ] `yarn --version` is %s\n' "${TO}" "${TO}")"
  printf '%s\n' "${body}" >"${body_file}"
  GITLAB_PIPELINE="${GITLAB_PIPELINE:-true}" \
    "${CREATE_PR_MR}" \
    --cwd "${dir}" \
    --base "${BRANCH}" \
    --head "${TOPIC}" \
    --title "${title}" \
    --body-file "${body_file}" \
    --label ok-to-test \
    --no-open \
    || echo "[WARN] create-pr-mr failed for ${slug}" >&2
  rm -f "${body_file}"
  popd >/dev/null
}

process_gh() {
  local slug="$1"
  local name dest
  name=$(basename "${slug}")
  dest="${WORKDIR}/${name}"
  echo "=== ${slug} ==="
  if ! clone_repo "$(github_clone_url "${slug}")" "${dest}"; then
    echo "[ERROR] clone failed ${slug}"; RC=1; return
  fi
  if has_open_gh_pr "${dest}"; then
    echo "[INFO] skip ${slug}: open ${TOPIC}* PR"; return
  fi
  local args=()
  bump_args "${dest}" args
  if ! node "${BUMP_JS}" "${args[@]}"; then
    echo "[ERROR] bump failed ${slug}"; RC=1; return
  fi
  if [[ -z "${GH_BIN_ROOT}" && -f "${dest}/.yarn/releases/yarn-${TO}.cjs" ]]; then
    GH_BIN_ROOT="${dest}"
  fi
  commit_and_pr "${dest}" "${slug}" || RC=1
}

process_gl() {
  local slug="$1"
  local name dest url host tok user
  name=$(basename "${slug}")
  dest="${WORKDIR}/gl-${name}"
  host="${CI_SERVER_HOST:-gitlab.cee.redhat.com}"
  tok="${PRIVATE_TOKEN:-}"
  user="${CI_PROJECT_NAME:-oauth2}"
  if [[ -n "${tok}" ]]; then
    url="https://${user}:${tok}@${host}/${slug}.git"
  else
    url="https://${host}/${slug}.git"
  fi
  echo "=== gitlab ${slug} ==="
  if ! clone_repo "${url}" "${dest}"; then
    echo "[ERROR] clone failed ${slug}"; RC=1; return
  fi
  if has_open_gl_mr "${slug}"; then
    echo "[INFO] skip ${slug}: open ${TOPIC}* MR"; return
  fi
  local args=()
  bump_args "${dest}" args
  if [[ -z "${YARN_BIN}" ]]; then
    if [[ -n "${GH_BIN_ROOT}" ]]; then
      args+=(--copy-bin "${GH_BIN_ROOT}")
    else
      echo "[WARN] no fetched yarn-${TO}.cjs and no GitHub copy; GL bump may fail without binary"
    fi
  fi
  if ! node "${BUMP_JS}" "${args[@]}"; then
    echo "[ERROR] bump failed ${slug}"; RC=1; return
  fi
  commit_and_pr "${dest}" "${slug}" || RC=1
}

for slug in "${GH_REPOS[@]}"; do process_gh "${slug}"; done
for slug in "${GL_REPOS[@]}"; do process_gl "${slug}"; done

echo "[INFO] yarn-bump done (rc=${RC})"
exit "${RC}"
