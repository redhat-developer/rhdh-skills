#!/usr/bin/env bash
# Push a topic branch and open a GitHub PR or GitLab CEE MR.
# Require attribution; add Jira metadata and link via sibling rhdh-jira-link
# only when an issue key is given (Jira-less automation omits it).
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SKILL_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
# Sibling skill scripts (override with RHDH_JIRA_LINK_SCRIPTS).
JIRA_LINK_SCRIPTS="${RHDH_JIRA_LINK_SCRIPTS:-$(cd "${SKILL_ROOT}/../../jira/rhdh-jira-link/scripts" 2>/dev/null && pwd || true)}"

CWD=""
BASE=""
HEAD=""
TITLE=""
BODY=""
BODY_FILE=""
ISSUE="${JIRA_ISSUE:-}"
ATTRIBUTION="${RHDH_ATTRIBUTION:-${RHDH_ASSISTED_BY:-}}"
LABEL=""
NO_OPEN=1
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  create-pr-mr.sh --cwd DIR --base BRANCH --head BRANCH --title TITLE
                  [--body TEXT | --body-file FILE]
                  [--issue KEY] --attribution ATTR
                  [--label LABEL] [--open] [--dry-run]

Caller owns the commit. This script pushes --head and opens a GitHub PR or
GitLab CEE MR. It verifies the latest commit carries an Assisted-By trailer,
adds the resolved attribution and — when --issue is given — a Markdown Jira
link to the description, and links Jira via rhdh-jira-link. Without --issue
the PR/MR opens with attribution only, for Jira-less automation.

ATTR is written as-is when it already starts with Assisted-By:/Generated-by:,
otherwise it is prefixed with "Assisted-By: ". Its payload is optional past
the tool name: write what is known, then stop.

Env: GITHUB_TOKEN|GH_TOKEN; PRIVATE_TOKEN; CI_SERVER_HOST; GITLAB_PIPELINE;
     JIRA_ISSUE; RHDH_ATTRIBUTION (RHDH_ASSISTED_BY accepted); JIRA_API_TOKEN;
     RHDH_JIRA_LINK_SCRIPTS; PI_MODEL and PI_REASONING_LEVEL as a fallback.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --cwd) CWD="${2:?}"; shift 2 ;;
    --base) BASE="${2:?}"; shift 2 ;;
    --head) HEAD="${2:?}"; shift 2 ;;
    --title) TITLE="${2:?}"; shift 2 ;;
    --body) BODY="${2:?}"; shift 2 ;;
    --body-file) BODY_FILE="${2:?}"; shift 2 ;;
    --issue) ISSUE="${2:?}"; shift 2 ;;
    --attribution | --assisted-by) ATTRIBUTION="${2:?}"; shift 2 ;;
    --label) LABEL="${2:?}"; shift 2 ;;
    --no-open) NO_OPEN=1; shift ;;
    --open) NO_OPEN=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

[[ -n "${CWD}" && -d "${CWD}" ]] || { echo "[ERROR] --cwd DIR required" >&2; exit 1; }
[[ -n "${BASE}" && -n "${HEAD}" && -n "${TITLE}" ]] || {
  echo "[ERROR] --base, --head, and --title are required" >&2
  exit 1
}
if [[ -n "${ISSUE}" && ! "${ISSUE}" =~ ^[A-Z][A-Z0-9]+-[0-9]+$ ]]; then
  echo "[ERROR] --issue KEY must look like RHIDP-12345" >&2
  exit 1
fi
# Attribution: tool name required, everything after it optional. Fill in from
# the running harness when the caller passed nothing, and never invent a
# placeholder value — an agent copies a placeholder verbatim.
if [[ -z "${ATTRIBUTION}" && -n "${PI_MODEL:-}" ]]; then
  ATTRIBUTION="pi (${PI_MODEL##*/}"
  [[ -n "${PI_REASONING_LEVEL:-}" ]] && ATTRIBUTION="${ATTRIBUTION}, thinking: ${PI_REASONING_LEVEL}"
  ATTRIBUTION="${ATTRIBUTION})"
fi
[[ -n "${ATTRIBUTION}" ]] || {
  echo "[ERROR] --attribution required: '<tool> (<agent> + <model> (<provider>), thinking: <level>)'" >&2
  echo "[ERROR] use only the parts you know, for example 'pi' or 'paseo (pi + DeepSeek V4.1 Flash (EnMaaS))'" >&2
  exit 1
}
if [[ "${ATTRIBUTION}" == *$'\n'* ]] || [[ ! "${ATTRIBUTION}" =~ [^[:space:]] ]]; then
  echo "[ERROR] --attribution must be a single non-blank line" >&2
  exit 1
fi
attribution_line="${ATTRIBUTION}"
if [[ ! "${attribution_line}" =~ ^(Assisted-By|Generated-by):[[:space:]] ]]; then
  attribution_line="Assisted-By: ${attribution_line}"
fi
if [[ -n "${BODY_FILE}" ]]; then
  [[ -f "${BODY_FILE}" ]] || { echo "[ERROR] --body-file not found: ${BODY_FILE}" >&2; exit 1; }
  BODY=$(cat "${BODY_FILE}")
fi
[[ -n "${BODY}" ]] || BODY="${TITLE}"

append_body_line() {
  local line="$1"
  if ! printf '%s\n' "${BODY}" | grep -Fqx "${line}"; then
    if [[ -n "${BODY}" ]]; then
      BODY="${BODY}"$'\n\n'
    fi
    BODY="${BODY}${line}"
  fi
}

jira_line=""
if [[ -n "${ISSUE}" ]]; then
  jira_url="https://redhat.atlassian.net/browse/${ISSUE}"
  jira_line="Related Jira: [${ISSUE}](${jira_url})"
fi
ensure_body_metadata() {
  if [[ -n "${jira_line}" ]]; then
    append_body_line "${jira_line}"
  fi
  # Accept any existing attribution trailer, whatever its payload.
  printf '%s\n' "${BODY}" | grep -Eiq '^(generated|assisted)-by:' || append_body_line "${attribution_line}"
}
ensure_body_metadata

# Keep parallel stream MRs distinct: "chore: … [release-2.1]".
branch_suffix=" [${BASE}]"
if [[ "${TITLE}" != *"${branch_suffix}" ]]; then
  TITLE="${TITLE}${branch_suffix}"
fi

if [[ "${GITLAB_PIPELINE:-}" == "true" ]]; then
  NO_OPEN=1
fi

cd "${CWD}"

if ! git log -1 --format=%B | git interpret-trailers --parse | grep -Eiq '^(generated|assisted)-by:'; then
  echo "[ERROR] latest commit must carry an attribution trailer, for example: ${attribution_line}" >&2
  exit 1
fi

origin=$(git remote get-url origin 2>/dev/null || true)
[[ -n "${origin}" ]] || { echo "[ERROR] no origin remote in ${CWD}" >&2; exit 1; }

host="github"
if [[ "${origin}" == *gitlab* ]] || [[ "${origin}" == *"${CI_SERVER_HOST:-gitlab.cee.redhat.com}"* ]]; then
  host="gitlab"
fi

# owner/repo or group/project (no .git)
repo_slug=$(printf '%s' "${origin}" | sed -E 's#.*[:/]([^/]+/[^/]+)(\.git)?$#\1#' | sed 's/\.git$//')
repo_short=$(basename "${repo_slug}")

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[INFO] dry-run: would push ${HEAD} → ${BASE} on ${host} ${repo_slug}"
  echo "[INFO] dry-run: title=${TITLE}"
  echo "[INFO] dry-run: description metadata:"
  if [[ -n "${jira_line}" ]]; then
    echo "${jira_line}"
  fi
  echo "${attribution_line}"
  if [[ -n "${ISSUE}" ]]; then
    echo "[INFO] dry-run: would link Jira ${ISSUE}"
  fi
  exit 0
fi

git checkout -B "${HEAD}" >/dev/null

# Rebase to the tip of the remote topic branch (when it exists) and the target
# branch before pushing, so the PR/MR never opens behind the base.
rebased=0
# Explicit refspec: single-branch clones (yarn-bump uses them) have a fetch
# refspec that covers only one branch, so a bare "git fetch origin HEAD"
# updates FETCH_HEAD without creating the tracking ref the rebase below
# relies on (RHIDP-18915).
if git fetch -q origin "+refs/heads/${HEAD}:refs/remotes/origin/${HEAD}" 2>/dev/null \
  && git rev-parse -q --verify "origin/${HEAD}" >/dev/null 2>&1; then
  if ! git rebase "origin/${HEAD}" >/dev/null 2>&1; then
    git rebase --abort 2>/dev/null || true
    # A bot-owned branch whose remote tip conflicts is disposable: both sides
    # are generated against the same base (e.g. two weekly yarn bumps), so a
    # conflicted rebase just means the remote copy is stale. Replace the tip
    # instead of failing the repo (RHIDP-18915).
    if [[ "${HEAD}" == chore/automated-* ]]; then
      echo "[INFO] rebase onto origin/${HEAD} hit conflicts; replacing the stale bot branch tip" >&2
      rebased=1
    else
      echo "[ERROR] rebase onto origin/${HEAD} hit conflicts; resolve, then rerun" >&2
      exit 1
    fi
  else
    rebased=1
  fi
fi
base_tip=""
for remote in origin upstream; do
  if git fetch -q "${remote}" "+refs/heads/${BASE}:refs/remotes/${remote}/${BASE}" 2>/dev/null \
    && git rev-parse -q --verify "${remote}/${BASE}" >/dev/null 2>&1; then
    base_tip="${remote}/${BASE}"
    break
  fi
done
if [[ -n "${base_tip}" ]] && ! git rebase "${base_tip}" >/dev/null 2>&1; then
  git rebase --abort 2>/dev/null || true
  echo "[ERROR] rebase onto ${base_tip} hit conflicts; resolve, then rerun" >&2
  exit 1
fi
# Never open a PR/MR that is still behind the base tip (no-op for a fast-forward).
if [[ -n "${base_tip}" ]] && ! git merge-base --is-ancestor "${base_tip}" HEAD; then
  echo "[ERROR] HEAD is not ahead of ${base_tip}; refusing to push" >&2
  exit 1
fi
# Keep push stderr out of the log only until it is needed: on failure print
# it with any embedded credentials redacted, so "push failed" stays
# diagnosable (RHIDP-18915).
push_err=$(mktemp)
push_rc=0
if [[ "${rebased}" -eq 1 ]]; then
  git push -u origin --force-with-lease "HEAD:${HEAD}" 2>"${push_err}" || push_rc=$?
else
  git push -u origin "HEAD:${HEAD}" 2>"${push_err}" || push_rc=$?
fi
if [[ "${push_rc}" -ne 0 ]]; then
  sed -E 's#(https?://)[^@/]+@#\1***@#g' "${push_err}" >&2
  echo "[ERROR] push failed for ${repo_slug}:${HEAD}" >&2
  rm -f "${push_err}"
  exit 1
fi
rm -f "${push_err}"

url=""
if [[ "${host}" == "github" ]]; then
  command -v gh >/dev/null || { echo "[ERROR] gh required for GitHub" >&2; exit 1; }
  existing=$(gh pr list --base "${BASE}" --head "${HEAD}" --state open --json url -q '.[0].url // empty' 2>/dev/null || true)
  if [[ -n "${existing}" ]]; then
    url="${existing}"
    if [[ ! "${url}" =~ /pull/([0-9]+)$ ]]; then
      echo "[ERROR] could not parse existing PR number: ${url}" >&2
      exit 1
    fi
    existing_pr_id="${BASH_REMATCH[1]}"
    if ! BODY=$(gh api "repos/${repo_slug}/pulls/${existing_pr_id}" --jq .body 2>/dev/null); then
      echo "[ERROR] could not read existing PR description: ${url}" >&2
      exit 1
    fi
    ensure_body_metadata
    if ! gh api "repos/${repo_slug}/pulls/${existing_pr_id}" --method PATCH \
      --raw-field body="${BODY}" >/dev/null 2>&1; then
      echo "[ERROR] could not update existing PR description: ${url}" >&2
      exit 1
    fi
    echo "[INFO] existing PR ${url}"
  else
    create_args=(pr create --base "${BASE}" --head "${HEAD}" --title "${TITLE}" --body "${BODY}")
    if [[ -n "${LABEL}" ]]; then
      create_args+=(--label "${LABEL}")
    fi
    url=$(gh "${create_args[@]}" 2>/dev/null || true)
    if [[ -z "${url}" ]]; then
      # retry without label (repo may lack it)
      url=$(gh pr create --base "${BASE}" --head "${HEAD}" --title "${TITLE}" --body "${BODY}" 2>/dev/null || true)
    fi
    [[ -n "${url}" ]] || { echo "[ERROR] gh pr create failed" >&2; exit 1; }
    echo "[INFO] opened ${url}"
  fi
  if [[ -n "${LABEL}" ]]; then
    if ! gh pr edit "${url}" --add-label "${LABEL}" 2>/dev/null; then
      if [[ "${LABEL}" == "ok-to-test" ]]; then
        gh pr comment "${url}" --body "/ok-to-test" 2>/dev/null || true
      fi
    fi
  fi
  if [[ "${NO_OPEN}" -eq 0 ]]; then
    gh pr view "${url}" --web 2>/dev/null || true
  fi
else
  # GitLab CEE
  glab_host="${CI_SERVER_HOST:-gitlab.cee.redhat.com}"
  tok="${PRIVATE_TOKEN:-}"
  if [[ -z "${tok}" ]] && command -v glab >/dev/null 2>&1; then
    # Keyring fallback: capture inside command substitution only; the token
    # never crosses stdout of this script. glab prints the token line on stderr.
    tok=$(glab auth status --hostname "${glab_host}" -t 2>&1 \
      | sed -nE 's/^.*keyring: ([A-Za-z0-9._-]+)$/\1/p; s/^Token:[[:space:]]+([A-Za-z0-9._-]+)$/\1/p' \
      | head -1)
  fi
  if [[ -z "${tok}" ]]; then
    echo "[ERROR] PRIVATE_TOKEN required for GitLab MR (or run: glab auth login --hostname ${glab_host})" >&2
    exit 1
  fi
  enc=$(printf '%s' "${repo_slug}" | jq -sRr @uri)
  # Confirm source-branch deletion took effect: GitLab 19 does not echo the
  # setting reliably in create/update responses (should_remove_source_branch
  # only shows up on later GETs, and the legacy remove_source_branch response
  # field is gone), so read the MR back and accept either response field.
  mr_removes_source_branch() {
    # mr_removes_source_branch <iid>
    local json
    json=$(curl -fsS --header "PRIVATE-TOKEN: ${tok}" \
      "https://${glab_host}/api/v4/projects/${enc}/merge_requests/$1" 2>/dev/null || true)
    [[ "$(jq -r '.should_remove_source_branch // .force_remove_source_branch // false' <<<"${json}" 2>/dev/null)" == "true" ]]
  }
  existing_json=$(curl -fsS --header "PRIVATE-TOKEN: ${tok}" \
    "https://${glab_host}/api/v4/projects/${enc}/merge_requests?state=opened&source_branch=${HEAD}" \
    | jq -c '.[0] // empty' 2>/dev/null || true)
  if [[ -n "${existing_json}" ]]; then
    url=$(jq -r '.web_url // empty' <<<"${existing_json}")
    mr_iid=$(jq -r '.iid // empty' <<<"${existing_json}")
    BODY=$(jq -r '.description // ""' <<<"${existing_json}")
    [[ -n "${url}" && -n "${mr_iid}" ]] || {
      echo "[ERROR] incomplete existing GitLab MR response" >&2
      exit 1
    }
    ensure_body_metadata
    curl -fsS --request PUT --header "PRIVATE-TOKEN: ${tok}" \
      --header "Content-Type: application/json" \
      --data "$(jq -n --arg body "${BODY}" '{description:$body,remove_source_branch:true,force_remove_source_branch:true}')" \
      "https://${glab_host}/api/v4/projects/${enc}/merge_requests/${mr_iid}" >/dev/null || true
    if ! mr_removes_source_branch "${mr_iid}"; then
      echo "[ERROR] existing GitLab MR did not enable source-branch deletion: ${url}" >&2
      exit 1
    fi
    echo "[INFO] existing MR ${url}"
  else
    created_json=$(curl -fsS --request POST --header "PRIVATE-TOKEN: ${tok}" \
      --header "Content-Type: application/json" \
      --data "$(jq -n --arg s "${HEAD}" --arg t "${BASE}" --arg title "${TITLE}" --arg body "${BODY}" \
        '{source_branch:$s,target_branch:$t,title:$title,description:$body,remove_source_branch:true,force_remove_source_branch:true}')" \
      "https://${glab_host}/api/v4/projects/${enc}/merge_requests" || true)
    url=$(jq -r '.web_url // empty' <<<"${created_json}" 2>/dev/null || true)
    [[ -n "${url}" ]] || { echo "[ERROR] GitLab MR create failed" >&2; exit 1; }
    mr_iid=$(jq -r '.iid // empty' <<<"${created_json}" 2>/dev/null || true)
    if ! mr_removes_source_branch "${mr_iid}"; then
      echo "[ERROR] new GitLab MR did not enable source-branch deletion: ${url}" >&2
      exit 1
    fi
    echo "[INFO] opened ${url}"
  fi
fi

echo "url: ${url}"

if [[ -z "${ISSUE}" ]]; then
  echo "[INFO] no --issue given; opened without Jira linkage"
  exit 0
fi

link_js="${JIRA_LINK_SCRIPTS}/link-pr-mr.js"
if [[ ! -f "${link_js}" ]]; then
  echo "[WARN] rhdh-jira-link script missing at ${link_js}; skip link" >&2
  exit 0
fi
if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  echo "[WARN] JIRA_API_TOKEN unset; skip link for ${ISSUE}" >&2
  exit 0
fi

# Extract numeric id from URL for title: repo #N: title
pr_id=""
if [[ "${url}" =~ /pull/([0-9]+) ]]; then
  pr_id="${BASH_REMATCH[1]}"
elif [[ "${url}" =~ /merge_requests/([0-9]+) ]]; then
  pr_id="${BASH_REMATCH[1]}"
fi
link_title="${repo_short}"
if [[ -n "${pr_id}" ]]; then
  link_title="${repo_short} #${pr_id}: ${TITLE}"
else
  link_title="${repo_short}: ${TITLE}"
fi

link_host_flag=()
if [[ "${host}" == "gitlab" ]]; then
  link_host_flag=(--host gitlab)
else
  link_host_flag=(--host github)
fi

if node "${link_js}" link --issue "${ISSUE}" --url "${url}" --title "${link_title}" \
  "${link_host_flag[@]}" 2>&1; then
  echo "[INFO] linked ${ISSUE} → ${url}"
else
  echo "[WARN] Jira link failed for ${ISSUE}; PR/MR remains at ${url}" >&2
fi

exit 0
