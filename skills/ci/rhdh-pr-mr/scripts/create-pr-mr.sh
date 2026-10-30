#!/usr/bin/env bash
# Push a topic branch and open a GitHub PR or GitLab CEE MR.
# Require attribution and Jira metadata, then link via sibling rhdh-jira-link.
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
ASSISTED_BY="${RHDH_ASSISTED_BY:-}"
LABEL=""
NO_OPEN=1
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  create-pr-mr.sh --cwd DIR --base BRANCH --head BRANCH --title TITLE
                  [--body TEXT | --body-file FILE]
                  --issue KEY --assisted-by ATTRIBUTION
                  [--label LABEL] [--open] [--dry-run]

Caller owns the commit. This script pushes --head and opens a GitHub PR or
GitLab CEE MR. It verifies the latest commit's Assisted-By trailer, adds the
same attribution and a Markdown Jira link to the description, and links Jira
via rhdh-jira-link.

Env: GITHUB_TOKEN|GH_TOKEN; PRIVATE_TOKEN; CI_SERVER_HOST; GITLAB_PIPELINE;
     JIRA_ISSUE; RHDH_ASSISTED_BY; JIRA_API_TOKEN; RHDH_JIRA_LINK_SCRIPTS.
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
    --assisted-by) ASSISTED_BY="${2:?}"; shift 2 ;;
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
[[ "${ISSUE}" =~ ^[A-Z][A-Z0-9]+-[0-9]+$ ]] || {
  echo "[ERROR] --issue KEY is required (for example RHIDP-12345)" >&2
  exit 1
}
[[ -n "${ASSISTED_BY}" ]] || {
  echo "[ERROR] --assisted-by ATTRIBUTION is required" >&2
  exit 1
}
if [[ "${ASSISTED_BY}" =~ $'\n' ]] || [[ ! "${ASSISTED_BY}" =~ [^[:space:]] ]]; then
  echo "[ERROR] --assisted-by must be a single non-blank line" >&2
  exit 1
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

jira_url="https://redhat.atlassian.net/browse/${ISSUE}"
jira_line="Related Jira: [${ISSUE}](${jira_url})"
assisted_by_line="Assisted-By: ${ASSISTED_BY}"
ensure_body_metadata() {
  append_body_line "${jira_line}"
  append_body_line "${assisted_by_line}"
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

if ! git log -1 --format=%B | git interpret-trailers --parse | grep -Fqx "${assisted_by_line}"; then
  echo "[ERROR] latest commit must contain trailer: ${assisted_by_line}" >&2
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
  echo "${jira_line}"
  echo "${assisted_by_line}"
  echo "[INFO] dry-run: would link Jira ${ISSUE}"
  exit 0
fi

git checkout -B "${HEAD}" >/dev/null
if ! git push -u origin "HEAD:${HEAD}" 2>/dev/null; then
  echo "[ERROR] push failed for ${repo_slug}:${HEAD}" >&2
  exit 1
fi

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
  if [[ -z "${tok}" ]]; then
    echo "[ERROR] PRIVATE_TOKEN required for GitLab MR" >&2
    exit 1
  fi
  enc=$(printf '%s' "${repo_slug}" | jq -sRr @uri)
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
    updated_json=$(curl -fsS --request PUT --header "PRIVATE-TOKEN: ${tok}" \
      --header "Content-Type: application/json" \
      --data "$(jq -n --arg body "${BODY}" '{description:$body,remove_source_branch:true}')" \
      "https://${glab_host}/api/v4/projects/${enc}/merge_requests/${mr_iid}" || true)
    if [[ "$(jq -r '.should_remove_source_branch // false' <<<"${updated_json}" 2>/dev/null)" != "true" ]]; then
      echo "[ERROR] existing GitLab MR did not enable source-branch deletion: ${url}" >&2
      exit 1
    fi
    echo "[INFO] existing MR ${url}"
  else
    created_json=$(curl -fsS --request POST --header "PRIVATE-TOKEN: ${tok}" \
      --header "Content-Type: application/json" \
      --data "$(jq -n --arg s "${HEAD}" --arg t "${BASE}" --arg title "${TITLE}" --arg body "${BODY}" \
        '{source_branch:$s,target_branch:$t,title:$title,description:$body,remove_source_branch:true}')" \
      "https://${glab_host}/api/v4/projects/${enc}/merge_requests" || true)
    url=$(jq -r '.web_url // empty' <<<"${created_json}" 2>/dev/null || true)
    [[ -n "${url}" ]] || { echo "[ERROR] GitLab MR create failed" >&2; exit 1; }
    if [[ "$(jq -r '.should_remove_source_branch // false' <<<"${created_json}" 2>/dev/null)" != "true" ]]; then
      echo "[ERROR] new GitLab MR did not enable source-branch deletion: ${url}" >&2
      exit 1
    fi
    echo "[INFO] opened ${url}"
  fi
fi

echo "url: ${url}"

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
