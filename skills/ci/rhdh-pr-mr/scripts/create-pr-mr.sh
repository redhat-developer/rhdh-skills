#!/usr/bin/env bash
# Push a topic branch and open a GitHub PR or GitLab CEE MR.
# Optionally link Jira via sibling rhdh-jira-link when --issue / JIRA_ISSUE is set.
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
LABEL=""
NO_OPEN=1
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  create-pr-mr.sh --cwd DIR --base BRANCH --head BRANCH --title TITLE
                  [--body TEXT | --body-file FILE]
                  [--issue KEY] [--label LABEL] [--open] [--dry-run]

Caller owns the commit. This script pushes --head and opens a GitHub PR or
GitLab CEE MR. If --issue or JIRA_ISSUE is set, links via rhdh-jira-link;
otherwise skips linking.

Env: GITHUB_TOKEN|GH_TOKEN; PRIVATE_TOKEN; CI_SERVER_HOST; GITLAB_PIPELINE;
     JIRA_ISSUE; JIRA_API_TOKEN; RHDH_JIRA_LINK_SCRIPTS.
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
if [[ -n "${BODY_FILE}" ]]; then
  [[ -f "${BODY_FILE}" ]] || { echo "[ERROR] --body-file not found: ${BODY_FILE}" >&2; exit 1; }
  BODY=$(cat "${BODY_FILE}")
fi
[[ -n "${BODY}" ]] || BODY="${TITLE}"

# Keep parallel stream MRs distinct: "chore: … [release-2.1]".
branch_suffix=" [${BASE}]"
if [[ "${TITLE}" != *"${branch_suffix}" ]]; then
  TITLE="${TITLE}${branch_suffix}"
fi

if [[ "${GITLAB_PIPELINE:-}" == "true" ]]; then
  NO_OPEN=1
fi

cd "${CWD}"

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
  if [[ -n "${ISSUE}" ]]; then
    echo "[INFO] dry-run: would link Jira ${ISSUE}"
  else
    echo "[INFO] no Jira issue; skip link"
  fi
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
  existing=$(curl -fsS --header "PRIVATE-TOKEN: ${tok}" \
    "https://${glab_host}/api/v4/projects/${enc}/merge_requests?state=opened&source_branch=${HEAD}" \
    | jq -r '.[0].web_url // empty' 2>/dev/null || true)
  if [[ -n "${existing}" ]]; then
    url="${existing}"
    echo "[INFO] existing MR ${url}"
  else
    url=$(curl -fsS --request POST --header "PRIVATE-TOKEN: ${tok}" \
      --header "Content-Type: application/json" \
      --data "$(jq -n --arg s "${HEAD}" --arg t "${BASE}" --arg title "${TITLE}" --arg body "${BODY}" \
        '{source_branch:$s,target_branch:$t,title:$title,description:$body,remove_source_branch:true}')" \
      "https://${glab_host}/api/v4/projects/${enc}/merge_requests" \
      | jq -r '.web_url // empty' 2>/dev/null || true)
    [[ -n "${url}" ]] || { echo "[ERROR] GitLab MR create failed" >&2; exit 1; }
    echo "[INFO] opened ${url}"
  fi
fi

echo "url: ${url}"

# Optional Jira link
if [[ -z "${ISSUE}" ]]; then
  echo "[INFO] no Jira issue; skip link"
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
