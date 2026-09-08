#!/usr/bin/env bash
#
# Update base images and RPM lockfiles in RHDH upstream GitHub repos.
# See the local rhdh-base-images SKILL.md.
#
# SPDX-License-Identifier: EPL-2.0

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

BRANCH=""
UPDATE_BASE_IMAGES_SCRIPT=""
RPM_LOCKFILE_PROTOTYPE=""
REPO_DIRS=()
SKIP_BASE=0
SKIP_RPM=0
DRY_RUN=0
ANALYZE=0
ALLOW_DIRTY=0
BASE_IMAGE_ARGS=(--pr --no-push)

GITLAB_SCRIPTS_BASE="https://gitlab.cee.redhat.com/rhidp/rhdh/-/raw"
CACHE_DIR="${XDG_CACHE_HOME:-${HOME}/.cache}/base-images-and-rpms"

usage() {
    cat <<'EOF'
Update base images, RPM lockfiles, Node headers, plugin-catalog builder pins,
and overlays versions.json node in the RHDH GitHub/GitLab checkouts.

Usage:
  base-images-and-rpms.sh -b BRANCH [OPTIONS] [REPO_DIR ...]
  base-images-and-rpms.sh --analyze [OPTIONS] [REPO_DIR ...]

Required (update mode):
  -b, --branch BRANCH       Branch to update: main or release-* (e.g. release-1.10)

Optional paths (fetch/install when omitted):
  --update-base-images-script PATH   Path to updateBaseImages.sh (needs createPR.sh alongside)
  --rpm-lockfile-prototype PATH      Path to rpm-lockfile-prototype binary

Repo selection (default: all three under --parent-dir, or current directory if it matches one repo):
  --parent-dir PATH         Directory containing local clones (e.g. ~/RHDH/)
  REPO_DIR ...              One or more repo checkouts to update

Workflow:
  --analyze                 Read-only scan (current vs latest tags, UBI skew); no -b required
  --skip-base               Skip updateBaseImages.sh
  --skip-rpm                Skip rpm-lockfile-prototype
  --dirty                   Pass --dirty to updateBaseImages.sh
  --push                    Allow updateBaseImages.sh to push (default: --pr --no-push)
  --no-pr                   Attempt direct push instead of opening a PR
  --dry-run                 Print actions without changing files

Examples:
  base-images-and-rpms.sh --analyze --parent-dir ~/RHDH
  base-images-and-rpms.sh -b release-1.10 --parent-dir ~/RHDH/
  base-images-and-rpms.sh -b main \
    --update-base-images-script ~/src/rhdh/build/scripts/updateBaseImages.sh \
    ~/RHDH/rhdh ~/RHDH/rhdh-operator ~/RHDH/rhdh-must-gather \
    ~/RHDH/rhdh-plugin-catalog ~/RHDH/rhdh-plugin-export-overlays
EOF
}

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

log() {
    echo "[INFO] $*" >&2
}

warn() {
    echo "[WARN] $*" >&2
}

validate_branch() {
    local branch="$1"
    if [[ "${branch}" == "main" ]] || [[ "${branch}" =~ ^release-.+ ]]; then
        return 0
    fi
    die "Invalid branch '${branch}'. Expected main or release-*"
}

scripts_branch_for() {
    local branch="$1"
    if [[ "${branch}" =~ ^release-(1\..+)$ ]]; then
        echo "rhdh-${BASH_REMATCH[1]}-rhel-9"
    else
        echo "${branch}"
    fi
}

is_git_checkout() {
    [[ -e "$1/.git" ]]
}

# GitHub -b selector → plugin-catalog GitLab branch.
# 1.Y uses rhdh-1.Y-rhel-N; 2.Y+ uses the same release-X.Y name as GitHub.
catalog_git_branch_for() {
    local branch="$1"
    if [[ "${branch}" == "main" ]]; then
        echo "main"
    elif [[ "${branch}" =~ ^release-(1\.[0-9]+)$ ]]; then
        echo "rhdh-${BASH_REMATCH[1]}-rhel-9"
    elif [[ "${branch}" =~ ^release- ]]; then
        echo "${branch}"
    else
        die "No plugin-catalog branch mapping for ${branch}"
    fi
}

detect_repo_kind() {
    local repo_dir="$1"
    if [[ -f "${repo_dir}/Containerfile" && -f "${repo_dir}/rpms.in.yaml" && -d "${repo_dir}/collection-scripts" ]]; then
        echo "rhdh-must-gather"
    elif [[ -f "${repo_dir}/go.mod" ]] \
        && grep -q '^module github.com/redhat-developer/rhdh-operator' "${repo_dir}/go.mod" 2>/dev/null; then
        echo "rhdh-operator"
    elif [[ -f "${repo_dir}/build/containerfiles/builder.Containerfile" && -f "${repo_dir}/.nvmrc" ]] \
        && { [[ -f "${repo_dir}/.tekton/updatePLRs.sh" ]] \
            || [[ -f "${repo_dir}/.tekton/generatePipelineRunsForPlugins.sh" ]]; }; then
        echo "rhdh-plugin-catalog"
    elif [[ -f "${repo_dir}/versions.json" ]] \
        && { [[ -d "${repo_dir}/workspaces" ]] || [[ -d "${repo_dir}/catalog-entities" ]]; } \
        && grep -q '"node"' "${repo_dir}/versions.json" 2>/dev/null; then
        echo "rhdh-plugin-export-overlays"
    elif [[ -f "${repo_dir}/rpms.in.yaml" ]] && [[ -f "${repo_dir}/package.json" ]]; then
        echo "rhdh"
    else
        echo "unknown"
    fi
}

rhdh_nodejs_containerfile() {
    local repo_dir="$1"
    if [[ -f "${repo_dir}/build/containerfiles/Containerfile" ]]; then
        echo "${repo_dir}/build/containerfiles/Containerfile"
    elif [[ -f "${repo_dir}/docker/Dockerfile" ]]; then
        echo "${repo_dir}/docker/Dockerfile"
    elif [[ -f "${repo_dir}/.rhdh/docker/Dockerfile" ]]; then
        echo "${repo_dir}/.rhdh/docker/Dockerfile"
    elif [[ -f "${repo_dir}/build/containerfiles/builder.Containerfile" ]]; then
        echo "${repo_dir}/build/containerfiles/builder.Containerfile"
    fi
}

rpm_containerfile_for() {
    local repo_dir="$1"
    local kind="$2"
    case "${kind}" in
        rhdh)
            if [[ -f "${repo_dir}/build/containerfiles/Containerfile" ]]; then
                echo "build/containerfiles/Containerfile"
            elif [[ -f "${repo_dir}/.rhdh/docker/Dockerfile" ]]; then
                echo ".rhdh/docker/Dockerfile"
            else
                die "${repo_dir}: no RPM containerfile found for rhdh"
            fi
            ;;
        rhdh-operator) echo ".rhdh/docker/Dockerfile" ;;
        rhdh-must-gather) echo "Containerfile" ;;
        rhdh-plugin-catalog | rhdh-plugin-export-overlays)
            die "${repo_dir}: ${kind} has no rpms.lock.yaml"
            ;;
        *) die "Unknown repo kind '${kind}'" ;;
    esac
}

ensure_tools() {
    local tool
    for tool in "$@"; do
        command -v "${tool}" >/dev/null 2>&1 || die "${tool} is required"
    done
}

fetch_gitlab_script() {
    local scripts_branch="$1"
    local script_name="$2"
    local dest_dir="$3"
    local url="${GITLAB_SCRIPTS_BASE}/${scripts_branch}/build/scripts/${script_name}"
    mkdir -p "${dest_dir}"
    if [[ ! -f "${dest_dir}/${script_name}" ]]; then
        log "Downloading ${script_name} from ${scripts_branch}"
        curl -fsSL "${url}" -o "${dest_dir}/${script_name}"
        chmod +x "${dest_dir}/${script_name}"
    fi
}

resolve_update_base_images_script() {
    local scripts_branch="$1"
    if [[ -n "${UPDATE_BASE_IMAGES_SCRIPT}" ]]; then
        [[ -f "${UPDATE_BASE_IMAGES_SCRIPT}" ]] || die "updateBaseImages.sh not found: ${UPDATE_BASE_IMAGES_SCRIPT}"
        [[ -x "${UPDATE_BASE_IMAGES_SCRIPT}" ]] || chmod +x "${UPDATE_BASE_IMAGES_SCRIPT}"
        local script_parent
        script_parent=$(cd "$(dirname "${UPDATE_BASE_IMAGES_SCRIPT}")" && pwd)
        if [[ ! -f "${script_parent}/createPR.sh" ]]; then
            fetch_gitlab_script "${scripts_branch}" "createPR.sh" "${script_parent}"
        fi
        echo "${UPDATE_BASE_IMAGES_SCRIPT}"
        return 0
    fi

    local cached_dir="${CACHE_DIR}/${scripts_branch}"
    fetch_gitlab_script "${scripts_branch}" "getLatestImageTags.sh" "${cached_dir}"
    fetch_gitlab_script "${scripts_branch}" "updateBaseImages.sh" "${cached_dir}"
    fetch_gitlab_script "${scripts_branch}" "createPR.sh" "${cached_dir}"
    echo "${cached_dir}/updateBaseImages.sh"
}

resolve_rpm_lockfile_prototype() {
    if [[ -n "${RPM_LOCKFILE_PROTOTYPE}" ]]; then
        [[ -x "${RPM_LOCKFILE_PROTOTYPE}" ]] || die "rpm-lockfile-prototype is not executable: ${RPM_LOCKFILE_PROTOTYPE}"
        echo "${RPM_LOCKFILE_PROTOTYPE}"
        return 0
    fi
    if [[ -x "${HOME}/.local/bin/rpm-lockfile-prototype" ]]; then
        echo "${HOME}/.local/bin/rpm-lockfile-prototype"
        return 0
    fi
    log "Installing rpm-lockfile-prototype to ${HOME}/.local/bin"
    mkdir -p "${HOME}/.local/bin"
    python3 -m pip install --user \
        https://github.com/konflux-ci/rpm-lockfile-prototype/archive/refs/heads/main.zip 2>/dev/null
    [[ -x "${HOME}/.local/bin/rpm-lockfile-prototype" ]] \
        || die "rpm-lockfile-prototype install failed; pass --rpm-lockfile-prototype PATH"
    echo "${HOME}/.local/bin/rpm-lockfile-prototype"
}

discover_repos_in_parent() {
    local parent="$1"
    local candidate kind
    for candidate in \
        "${parent}/1-rhdh" "${parent}/rhdh" \
        "${parent}/1-rhdh-operator" "${parent}/rhdh-operator" \
        "${parent}/1-must-gather" "${parent}/1-rhdh-must-gather" "${parent}/rhdh-must-gather" \
        "${parent}/1-rhdh-plugin-catalog" "${parent}/rhdh-plugin-catalog" \
        "${parent}/1-overlays" "${parent}/rhdh-plugin-export-overlays"; do
        is_git_checkout "${candidate}" || continue
        kind=$(detect_repo_kind "${candidate}")
        [[ "${kind}" != "unknown" ]] || continue
        REPO_DIRS+=("${candidate}")
    done
}

checkout_branch() {
    local repo_dir="$1"
    local branch="$2"
    pushd "${repo_dir}" >/dev/null
    git fetch origin "${branch}" 2>/dev/null || true
    if git show-ref --verify --quiet "refs/remotes/origin/${branch}"; then
        git checkout "${branch}"
        git pull --ff-only origin "${branch}" 2>/dev/null || true
    elif git show-ref --verify --quiet "refs/heads/${branch}"; then
        git checkout "${branch}"
    else
        popd >/dev/null
        die "${repo_dir}: branch ${branch} not found"
    fi
    popd >/dev/null
}

update_base_images() {
    local repo_dir="$1"
    local branch="$2"
    local scripts_branch="$3"
    local update_script="$4"
    local extra=()
    [[ ${ALLOW_DIRTY} -eq 1 ]] && extra+=(--dirty)

    log "Base images: $(basename "${repo_dir}") @ ${branch} (scripts branch ${scripts_branch})"
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  dry-run: ${update_script} -w ${repo_dir} -b ${branch} -sb ${scripts_branch} -maxdepth 5 ${BASE_IMAGE_ARGS[*]} ${extra[*]}"
        return 0
    fi

    pushd "${repo_dir}" >/dev/null
    git config user.name "rhdh-bot" 2>/dev/null || true
    git config user.email "rhdh-bot@redhat.com" 2>/dev/null || true
    popd >/dev/null

    # createPR.sh runs `gh pr view --web` on every createPr() call; updateBaseImages.sh
    # calls createPr once per image bump. Suppress repeated browser opens and show once below.
    GITLAB_PIPELINE=true "${update_script}" -w "${repo_dir}" -b "${branch}" -sb "${scripts_branch}" \
        -maxdepth 5 "${BASE_IMAGE_ARGS[@]}" "${extra[@]}" \
        || warn "updateBaseImages.sh reported no change or failed for ${repo_dir}"

    if [[ " ${BASE_IMAGE_ARGS[*]} " == *" --pr "* ]]; then
        open_automation_pr_in_browser "${repo_dir}" "${branch}"
    fi
}

open_automation_pr_in_browser() {
    local repo_dir="$1"
    local branch="$2"
    local pr_branch

    command -v gh >/dev/null 2>&1 || return 0
    pushd "${repo_dir}" >/dev/null
    pr_branch=$(find_open_base_images_pr_branch "${branch}" || true)
    if [[ -n "${pr_branch}" ]]; then
        log "Opening PR once for ${branch} (${pr_branch})"
        gh pr view "${pr_branch}" --web 2>/dev/null || true
    fi
    popd >/dev/null
}

# rpm-lockfile-prototype logs this when a binary RPM has no matching source RPM
# in repo metadata (common for kernel-headers, efi-srpm-macros). The binary
# lockfile is still valid; never surface those lines to the agent.
filter_rpm_lockfile_source_warnings() {
    grep -viE -- 'no sources found for |no matching sources' || true
}

update_rpm_lockfile() {
    local repo_dir="$1"
    local kind="$2"
    local rpm_tool="$3"
    local branch="$4"
    local containerfile rpm_err rpm_rc
    containerfile=$(rpm_containerfile_for "${repo_dir}" "${kind}")

    [[ -f "${repo_dir}/${containerfile}" ]] || die "${repo_dir}: missing ${containerfile}"
    [[ -f "${repo_dir}/rpms.in.yaml" ]] || die "${repo_dir}: missing rpms.in.yaml"

    log "RPM lockfile: $(basename "${repo_dir}") using ${containerfile}"
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  dry-run: (cd ${repo_dir} && ${rpm_tool} -f ${containerfile} rpms.in.yaml)"
        echo "  dry-run: commit and push rpms.lock.yaml to open base-images PR branch (or chore/automated-update-rpm-lockfile/${branch})"
        return 0
    fi

    pushd "${repo_dir}" >/dev/null
    rpm_err=$(mktemp)
    rpm_rc=0
    "${rpm_tool}" -f "${containerfile}" rpms.in.yaml 2>"${rpm_err}" || rpm_rc=$?
    filter_rpm_lockfile_source_warnings <"${rpm_err}" >&2
    rm -f "${rpm_err}"
    if [[ ${rpm_rc} -ne 0 ]]; then
        warn "rpm-lockfile-prototype failed for ${repo_dir}; keeping existing rpms.lock.yaml"
    fi
    commit_push_rpm_lockfile "${branch}"
    popd >/dev/null
}

find_open_base_images_pr_branch() {
    local base_branch="$1"
    if ! command -v gh >/dev/null 2>&1; then
        return 0
    fi
    gh pr list --base "${base_branch}" --state open --author "rhdh-bot" \
        --json headRefName \
        --jq '.[] | select(.headRefName | startswith("chore/automated-update-base-images")) | .headRefName' \
        2>/dev/null | head -n1
}

ensure_automation_branch() {
    local branch="$1"
    local current
    current=$(git rev-parse --abbrev-ref HEAD)

    if [[ "${current}" != "${branch}" ]]; then
        printf '%s\n' "${current}"
        return 0
    fi

    local pr_branch
    pr_branch=$(find_open_base_images_pr_branch "${branch}" || true)
    if [[ -n "${pr_branch}" ]]; then
        log "Switching to open base-images PR branch ${pr_branch}" >&2
        git checkout "${pr_branch}" >/dev/null
        printf '%s\n' "${pr_branch}"
        return 0
    fi

    local rpm_branch="chore/automated-update-rpm-lockfile/${branch}"
    log "No automation PR branch; using ${rpm_branch}" >&2
    git checkout -B "${rpm_branch}" >/dev/null
    printf '%s\n' "${rpm_branch}"
}

commit_push_paths() {
    local branch="$1"
    local message="$2"
    shift 2
    local paths=("$@")

    if [[ ${#paths[@]} -eq 0 ]]; then
        return 0
    fi

    local has_changes=0 path
    for path in "${paths[@]}"; do
        if ! git diff --quiet -- "${path}" 2>/dev/null \
            || ! git diff --cached --quiet -- "${path}" 2>/dev/null \
            || [[ -n "$(git ls-files --others --exclude-standard -- "${path}")" ]]; then
            has_changes=1
            break
        fi
    done
    if [[ ${has_changes} -eq 0 ]]; then
        return 0
    fi

    local current push_branch
    current=$(git rev-parse --abbrev-ref HEAD)
    push_branch="${current}"

    if [[ "${current}" == "${branch}" ]]; then
        # Capture only the branch name; git checkout/hooks must not leak into the refspec.
        push_branch=$(ensure_automation_branch "${branch}" | tail -n1)
    fi

    git add "${paths[@]}"
    if git diff --cached --quiet; then
        log "Nothing to commit for: ${paths[*]}"
        return 0
    fi

    git commit -s -m "${message}"
    git push -u origin "${push_branch}"
    log "Pushed ${message} to origin/${push_branch}"

    if [[ "${push_branch}" == chore/automated-update-rpm-lockfile/* ]] \
        && command -v gh >/dev/null 2>&1 \
        && ! gh pr list --head "${push_branch}" --state open --json number -q '.[0].number' 2>/dev/null | grep -q .; then
        gh pr create \
            --base "${branch}" \
            --head "${push_branch}" \
            --title "chore: update RPM lockfile in branch (${branch}) [skip-build]" \
            --body "Automated RPM lockfile refresh from base-images-and-rpms.sh." \
            2>/dev/null \
            || warn "Could not open RPM lockfile PR for ${push_branch}"
    fi
}

rhdh_nodejs_builder_image() {
    local containerfile="$1"
    grep -E '^FROM registry\.access\.redhat\.com/ubi[0-9]+/nodejs-[0-9]+:' "${containerfile}" \
        | grep -v minimal | head -1 | awk '{print $2}'
}

node_version_from_image() {
    local image="$1"
    local runner=podman
    command -v podman >/dev/null 2>&1 || runner=docker
    "${runner}" run --rm --entrypoint node "${image}" --version 2>/dev/null | tr -d '\n\r'
}

update_nvm_releases_readme() {
    local readme="$1"
    local node_version="$2"
    local today
    today=$(date +%Y/%m/%d)

    [[ -f "${readme}" ]] || return 0

    sed -i \
        -e "s|^As of [0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9], this version is \`v[^']*\`|As of ${today}, this version is \`${node_version}\`|" \
        -e "s|^The latest RPM is \`v[^']*\`\.|The latest RPM is \`${node_version}\`.|" \
        -e "s|^NODE_HEADERS_VERSION=v[0-9].*|NODE_HEADERS_VERSION=${node_version}|" \
        "${readme}"
    # Example `node --version` output in the first code block.
    sed -i -E "s/^v[0-9]+\\.[0-9]+\\.[0-9]+$/$(printf '%s' "${node_version}")/" "${readme}"
}

nvm_readme_documents_version() {
    local readme="$1"
    local node_version="$2"
    [[ -f "${readme}" ]] || return 1
    grep -q "this version is \`${node_version}\`" "${readme}" 2>/dev/null
}

update_rhdh_node_headers() {
    local repo_dir="$1"
    local branch="$2"
    local containerfile
    containerfile=$(rhdh_nodejs_containerfile "${repo_dir}")

    [[ -n "${containerfile}" && -f "${containerfile}" ]] || return 0

    local image
    image=$(rhdh_nodejs_builder_image "${containerfile}")
    if [[ -z "${image}" ]]; then
        log "Node headers: no ubi*/nodejs builder image in Containerfile"
        return 0
    fi

    log "Node headers: checking node version from ${image##*/}"
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  dry-run: podman/docker run ${image} --version; refresh .nvm/releases, .nvmrc, README.adoc if changed"
        return 0
    fi

    if ! command -v podman >/dev/null 2>&1 && ! command -v docker >/dev/null 2>&1; then
        warn "Node headers: podman or docker required; skipping"
        return 0
    fi

    pushd "${repo_dir}" >/dev/null

    local node_version node_version_plain headers_file readme_file current_nvmrc old
    node_version=$(node_version_from_image "${image}") || true
    if [[ -z "${node_version}" ]]; then
        warn "Node headers: could not read node version from ${image}"
        popd >/dev/null
        return 0
    fi

    node_version_plain="${node_version#v}"
    headers_file=".nvm/releases/node-${node_version}-headers.tar.gz"
    readme_file=".nvm/releases/README.adoc"
    current_nvmrc=""
    [[ -f .nvmrc ]] && current_nvmrc=$(tr -d '\n\r' < .nvmrc)

    if [[ -f "${headers_file}" && "${current_nvmrc}" == "${node_version_plain}" ]] \
        && nvm_readme_documents_version "${readme_file}" "${node_version}"; then
        log "Node headers: already up to date (${node_version})"
        popd >/dev/null
        return 0
    fi

    log "Node headers: updating to ${node_version} (was ${current_nvmrc:-unset})"
    mkdir -p .nvm/releases
    curl -fsSL "https://nodejs.org/dist/${node_version}/node-${node_version}-headers.tar.gz" \
        -o "${headers_file}"
    echo "${node_version_plain}" > .nvmrc
    update_nvm_releases_readme "${readme_file}" "${node_version}"

    for old in .nvm/releases/node-v*-headers.tar.gz; do
        [[ -e "${old}" && "${old}" != "${headers_file}" ]] || continue
        if git ls-files --error-unmatch "${old}" >/dev/null 2>&1; then
            git rm -f "${old}"
        else
            rm -f "${old}"
        fi
    done

    commit_push_paths "${branch}" "chore: update node headers to ${node_version} [skip-build]" \
        .nvmrc "${headers_file}" "${readme_file}"
    popd >/dev/null
}

pin_catalog_builder_from() {
    local catalog_cf="$1"
    local src_image="$2"
    python3 - "${catalog_cf}" "${src_image}" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
image = sys.argv[2]
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"^FROM registry\.access\.redhat\.com/ubi[0-9]+/nodejs-[0-9]+:\S+",
    re.MULTILINE,
)
match = pattern.search(text)
if match is None:
    raise SystemExit("no ubi*/nodejs FROM line in catalog builder.Containerfile")
replacement = f"FROM {image}"
if match.group(0) == replacement:
    raise SystemExit(0)
path.write_text(pattern.sub(replacement, text, count=1), encoding="utf-8")
PY
}

rewrite_catalog_additional_tags() {
    local catalog_cf="$1"
    local node_plain="$2"
    sed -i -E "s/node-v[0-9]+\\.[0-9]+\\.[0-9]+/node-v${node_plain}/" "${catalog_cf}"
}

copy_nvm_tree() {
    local src="$1"
    local dest="$2"
    local old
    mkdir -p "${dest}/.nvm/releases"
    /bin/cp -f "${src}/.nvmrc" "${dest}/.nvmrc"
    if [[ -f "${src}/.nvm/releases/README.adoc" ]]; then
        /bin/cp -f "${src}/.nvm/releases/README.adoc" "${dest}/.nvm/releases/README.adoc"
    fi
    for old in "${src}"/.nvm/releases/node-v*-headers.tar.gz; do
        [[ -e "${old}" ]] || continue
        /bin/cp -f "${old}" "${dest}/.nvm/releases/"
    done
}

remove_stale_header_tarballs() {
    local keep="$1"
    local old
    for old in .nvm/releases/node-v*-headers.tar.gz; do
        [[ -e "${old}" && "${old}" != "${keep}" ]] || continue
        if git ls-files --error-unmatch "${old}" >/dev/null 2>&1; then
            git rm -f "${old}"
        else
            rm -f "${old}"
        fi
    done
}

update_plugin_catalog_node() {
    local repo_dir="$1"
    local git_branch="$2"
    local rhdh_src="${3:-}"
    local catalog_cf="${repo_dir}/build/containerfiles/builder.Containerfile"
    [[ -f "${catalog_cf}" ]] || return 0

    local src_image="" node_plain="" headers_file
    if [[ -n "${rhdh_src}" && -f "${rhdh_src}/.nvmrc" ]]; then
        src_image=$(rhdh_nodejs_builder_image "$(rhdh_nodejs_containerfile "${rhdh_src}")")
        node_plain=$(tr -d '\n\r' < "${rhdh_src}/.nvmrc")
    fi

    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  dry-run: pin ${catalog_cf} FROM to rhdh UBI node image; copy .nvm/; rewrite konflux.additional-tags node-v*"
        return 0
    fi

    pushd "${repo_dir}" >/dev/null
    if [[ -n "${src_image}" ]]; then
        pin_catalog_builder_from "${catalog_cf}" "${src_image}"
        copy_nvm_tree "${rhdh_src}" "${repo_dir}"
    else
        log "plugin-catalog: no rhdh checkout in this run; refreshing headers from catalog FROM"
        update_rhdh_node_headers "${repo_dir}" "${git_branch}"
        [[ -f .nvmrc ]] && node_plain=$(tr -d '\n\r' < .nvmrc)
    fi

    if [[ -n "${node_plain}" ]]; then
        rewrite_catalog_additional_tags "${catalog_cf}" "${node_plain}"
        headers_file=".nvm/releases/node-v${node_plain}-headers.tar.gz"
        remove_stale_header_tarballs "${headers_file}"
        commit_push_paths "${git_branch}" "chore: pin catalog builder to Node v${node_plain}" \
            .nvmrc "${headers_file}" .nvm/releases/README.adoc "${catalog_cf}"
    fi
    popd >/dev/null
}

update_overlays_node_version() {
    local repo_dir="$1"
    local git_branch="$2"
    local node_plain="${3:-}"
    local versions="${repo_dir}/versions.json"

    [[ -f "${versions}" ]] || return 0
    if [[ -z "${node_plain}" ]]; then
        warn "overlays: no Node version from rhdh/.nvmrc; skipping versions.json"
        return 0
    fi

    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  dry-run: set ${versions} node=${node_plain}"
        return 0
    fi

    pushd "${repo_dir}" >/dev/null
    python3 - "${versions}" "${node_plain}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
wanted = sys.argv[2]
data = json.loads(path.read_text(encoding="utf-8"))
if data.get("node") == wanted:
    raise SystemExit(0)
data["node"] = wanted
path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
PY
    commit_push_paths "${git_branch}" "chore: bump versions.json Node to ${node_plain}" versions.json
    popd >/dev/null
}

operator_go_toolset_image() {
    local dockerfile="$1"
    grep -E '^FROM registry\.access\.redhat\.com/ubi(9|10)/go-toolset:' "${dockerfile}" \
        | head -1 | awk '{print $2}'
}

go_version_from_toolset_image() {
    local image="$1"
    local runner=podman
    command -v podman >/dev/null 2>&1 || runner=docker
    "${runner}" run --rm --entrypoint go "${image}" version 2>/dev/null \
        | awk '{print $3}' | sed 's/^go//'
}

go_mod_language_version() {
    local full="$1"
    local major minor
    IFS=. read -r major minor _ <<< "${full}"
    echo "${major}.${minor}.0"
}

# Return 0 if version $1 is greater than or equal to version $2.
# Accepts optional "go" prefix. Empty operands are not greater-or-equal.
go_version_gte() {
    local left="${1#go}" right="${2#go}"
    [[ -n "${left}" && -n "${right}" ]] || return 1
    [[ "$(printf '%s\n%s\n' "${left}" "${right}" | sort -V | tail -n1)" == "${left}" ]]
}

update_operator_go_mod() {
    local repo_dir="$1"
    local branch="$2"
    local dockerfile="${repo_dir}/.rhdh/docker/Dockerfile"

    if [[ "${branch}" != "main" ]]; then
        log "Go toolchain: skipping go.mod update on ${branch} (main only)"
        return 0
    fi

    [[ -f "${repo_dir}/go.mod" && -f "${dockerfile}" ]] || return 0

    local image
    image=$(operator_go_toolset_image "${dockerfile}")
    [[ -n "${image}" ]] || return 0

    log "Go toolchain: checking version from ${image##*/}"
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "  dry-run: align go.mod with go version from ${image}"
        return 0
    fi

    if ! command -v podman >/dev/null 2>&1 && ! command -v docker >/dev/null 2>&1; then
        warn "Go toolchain: podman or docker required; skipping go.mod update"
        return 0
    fi

    pushd "${repo_dir}" >/dev/null

    local go_full go_lang current_toolchain
    go_full=$(go_version_from_toolset_image "${image}") || true
    if [[ -z "${go_full}" ]]; then
        warn "Go toolchain: could not read go version from ${image}"
        popd >/dev/null
        return 0
    fi

    go_lang=$(go_mod_language_version "${go_full}")
    current_toolchain=$(grep -E '^toolchain ' go.mod 2>/dev/null | awk '{print $2}' || true)
    local current_go current_plain bump_go=0 bump_toolchain=0
    current_go=$(grep -E '^go ' go.mod 2>/dev/null | awk '{print $2}' || true)
    current_plain="${current_toolchain#go}"

    # Never lower go.mod to match an older toolset image. A newer toolchain
    # (for example from Renovate) is valid in Konflux local-toolchain mode.
    if [[ -z "${current_go}" ]] || ! go_version_gte "${current_go}" "${go_lang}"; then
        bump_go=1
    fi
    if [[ -z "${current_plain}" ]] || ! go_version_gte "${current_plain}" "${go_full}"; then
        bump_toolchain=1
    fi

    if [[ ${bump_go} -eq 0 && ${bump_toolchain} -eq 0 ]]; then
        if [[ "${current_plain}" == "${go_full}" ]]; then
            log "Go toolchain: already aligned with go${go_full}"
        else
            log "Go toolchain: keeping ${current_toolchain} (newer than image go${go_full}; will not downgrade)"
        fi
        popd >/dev/null
        return 0
    fi

    log "Go toolchain: updating go.mod to go ${go_lang} / toolchain go${go_full} (forward only)"
    if [[ ${bump_go} -eq 1 ]]; then
        sed -i -e "s/^go .*/go ${go_lang}/" go.mod
    fi
    if [[ ${bump_toolchain} -eq 1 ]]; then
        sed -i -e "s/^toolchain .*/toolchain go${go_full}/" go.mod
    fi

    commit_push_paths "${branch}" "chore: align go.mod with ${image%%:*} go${go_full} [skip-build]" go.mod
    popd >/dev/null
}

run_analyze() {
    local scripts_branch="$1"
    local update_script scripts_dir analyze_script repo_dir

    ensure_tools skopeo
    update_script=$(resolve_update_base_images_script "${scripts_branch}")
    scripts_dir=$(dirname "${update_script}")
    fetch_gitlab_script "${scripts_branch}" "getLatestImageTags.sh" "${scripts_dir}"

    analyze_script="${SCRIPT_DIR}/analyze-base-images.sh"
    [[ -x "${analyze_script}" ]] || chmod +x "${analyze_script}"

    local -a analyze_args=(-s "${scripts_dir}")
    for repo_dir in "${REPO_DIRS[@]}"; do
        analyze_args+=(-w "$(cd "${repo_dir}" && pwd)")
    done

    "${analyze_script}" "${analyze_args[@]}"
}

commit_push_rpm_lockfile() {
    local branch="$1"

    if git diff --quiet rpms.lock.yaml 2>/dev/null \
        && git diff --cached --quiet rpms.lock.yaml 2>/dev/null; then
        log "RPM lockfile: no changes in rpms.lock.yaml"
        return 0
    fi

    local current
    current=$(git rev-parse --abbrev-ref HEAD)
    if [[ "${current}" == "${branch}" ]]; then
        local pr_branch
        pr_branch=$(find_open_base_images_pr_branch "${branch}" || true)
        if [[ -n "${pr_branch}" ]]; then
            log "RPM lockfile: attaching to open base-images PR branch ${pr_branch}"
            git stash push -m "rpm-lock" -- rpms.lock.yaml
            git checkout "${pr_branch}"
            git stash pop || true
        else
            ensure_automation_branch "${branch}" >/dev/null
        fi
    fi

    commit_push_paths "${branch}" "chore: update rpms.lock.yaml [skip-build]" rpms.lock.yaml
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--branch) BRANCH="$2"; shift 2 ;;
        --update-base-images-script) UPDATE_BASE_IMAGES_SCRIPT="$2"; shift 2 ;;
        --rpm-lockfile-prototype) RPM_LOCKFILE_PROTOTYPE="$2"; shift 2 ;;
        --parent-dir)
            discover_repos_in_parent "$2"
            shift 2
            ;;
        --skip-base) SKIP_BASE=1; shift ;;
        --skip-rpm) SKIP_RPM=1; shift ;;
        --dirty) ALLOW_DIRTY=1; shift ;;
        --push)
            BASE_IMAGE_ARGS=(--pr)
            shift
            ;;
        --no-pr)
            BASE_IMAGE_ARGS=(--no-push)
            shift
            ;;
        --dry-run) DRY_RUN=1; shift ;;
        --analyze) ANALYZE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        -*) die "Unknown option: $1 (try --help)" ;;
        *)
            [[ -e "$1/.git" ]] || die "Not a git repo: $1"
            REPO_DIRS+=("$1")
            shift
            ;;
    esac
done

while [[ $# -gt 0 ]]; do
    is_git_checkout "$1" || die "Not a git repo: $1"
    REPO_DIRS+=("$1")
    shift
done

if [[ ${ANALYZE} -eq 0 ]]; then
    [[ -n "${BRANCH}" ]] || { usage; exit 1; }
    validate_branch "${BRANCH}"
elif [[ -z "${BRANCH}" ]]; then
    BRANCH="main"
else
    validate_branch "${BRANCH}"
fi

if [[ ${#REPO_DIRS[@]} -eq 0 ]]; then
    if is_git_checkout "." && [[ "$(detect_repo_kind "$(pwd)")" != "unknown" ]]; then
        REPO_DIRS=("$(pwd)")
    else
        die "No repo directories found. Pass REPO_DIR paths or --parent-dir."
    fi
fi

SCRIPTS_BRANCH=$(scripts_branch_for "${BRANCH}")

if [[ ${ANALYZE} -eq 1 ]]; then
    run_analyze "${SCRIPTS_BRANCH}"
    exit 0
fi

if [[ ${SKIP_BASE} -eq 0 ]]; then
    ensure_tools jq skopeo curl
    command -v gh >/dev/null 2>&1 || warn "gh not found; --pr will fail if updateBaseImages.sh needs to open a PR"
fi

UPDATE_SCRIPT=""
RPM_TOOL=""
if [[ ${SKIP_BASE} -eq 0 ]]; then
    UPDATE_SCRIPT=$(resolve_update_base_images_script "${SCRIPTS_BRANCH}")
fi
if [[ ${SKIP_RPM} -eq 0 ]]; then
    RPM_TOOL=$(resolve_rpm_lockfile_prototype)
fi
command -v gh >/dev/null 2>&1 || warn "gh not found; automation commits may not reach an open PR"

order_repo_dirs() {
    local -a ordered=()
    local want d
    for want in rhdh rhdh-operator rhdh-must-gather rhdh-plugin-catalog rhdh-plugin-export-overlays; do
        for d in "${REPO_DIRS[@]}"; do
            if [[ "$(detect_repo_kind "${d}")" == "${want}" ]]; then
                ordered+=("${d}")
            fi
        done
    done
    REPO_DIRS=("${ordered[@]}")
}

order_repo_dirs

RHDH_NODE_REPO=""
RHDH_NODE_PLAIN=""

declare -A SEEN_KIND=()
for repo_dir in "${REPO_DIRS[@]}"; do
    repo_dir=$(cd "${repo_dir}" && pwd)
    kind=$(detect_repo_kind "${repo_dir}")
    [[ "${kind}" != "unknown" ]] || die "${repo_dir}: cannot detect repo type (rhdh, rhdh-operator, rhdh-must-gather, rhdh-plugin-catalog, or rhdh-plugin-export-overlays)"
    if [[ -n "${SEEN_KIND[${kind}]:-}" ]]; then
        warn "Skipping duplicate ${kind} repo: ${repo_dir}"
        continue
    fi
    SEEN_KIND[${kind}]=1

    local_git_branch="${BRANCH}"
    if [[ "${kind}" == "rhdh-plugin-catalog" ]]; then
        local_git_branch=$(catalog_git_branch_for "${BRANCH}")
    fi

    echo "=================================================="
    log "Processing ${kind} (${repo_dir}) @ ${local_git_branch}"
    if [[ ${DRY_RUN} -eq 1 ]]; then
        log "dry-run: would checkout ${local_git_branch} in ${repo_dir}"
    else
        checkout_branch "${repo_dir}" "${local_git_branch}"
    fi

    if [[ ${SKIP_BASE} -eq 0 \
        && "${kind}" != "rhdh-plugin-export-overlays" \
        && "${kind}" != "rhdh-plugin-catalog" ]]; then
        update_base_images "${repo_dir}" "${local_git_branch}" "${SCRIPTS_BRANCH}" "${UPDATE_SCRIPT}"
    fi
    if [[ ${SKIP_RPM} -eq 0 \
        && "${kind}" != "rhdh-plugin-catalog" \
        && "${kind}" != "rhdh-plugin-export-overlays" ]]; then
        update_rpm_lockfile "${repo_dir}" "${kind}" "${RPM_TOOL}" "${local_git_branch}"
    fi
    if [[ "${kind}" == "rhdh" ]]; then
        update_rhdh_node_headers "${repo_dir}" "${local_git_branch}"
        RHDH_NODE_REPO="${repo_dir}"
        [[ -f "${repo_dir}/.nvmrc" ]] && RHDH_NODE_PLAIN=$(tr -d '\n\r' < "${repo_dir}/.nvmrc")
    fi
    if [[ "${kind}" == "rhdh-operator" ]]; then
        update_operator_go_mod "${repo_dir}" "${local_git_branch}"
    fi
    if [[ "${kind}" == "rhdh-plugin-catalog" ]]; then
        update_plugin_catalog_node "${repo_dir}" "${local_git_branch}" "${RHDH_NODE_REPO}"
        [[ -f "${repo_dir}/.nvmrc" ]] && RHDH_NODE_PLAIN=$(tr -d '\n\r' < "${repo_dir}/.nvmrc")
    fi
    if [[ "${kind}" == "rhdh-plugin-export-overlays" ]]; then
        update_overlays_node_version "${repo_dir}" "${local_git_branch}" "${RHDH_NODE_PLAIN}"
    fi
done

log "Done. Review open PRs for base image, RPM lockfile, node header, catalog builder, overlays, and go.mod updates."
