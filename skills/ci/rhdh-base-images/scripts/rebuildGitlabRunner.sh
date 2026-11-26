#!/usr/bin/env bash
#
# Copyright (c) 2026 Red Hat, Inc.
# This program and the accompanying materials are made
# available under the terms of the Eclipse Public License 2.0
# which is available at https://www.eclipse.org/legal/epl-2.0/
#
# SPDX-License-Identifier: EPL-2.0
#
# Rebuild quay.io/rhdh/gitlab-runner from a published plugin-catalog-builder
# image, and optionally re-pin .gitlab-ci.yml in repos that run on it.
#
# Part of rhdh-base-images; see workflows/gitlab-runner-rebuild.md.
# The agent-driven steps (waiting for the builder MR to merge, waiting for the
# Konflux push PipelineRun, opening and merging MRs) live in the workflow doc;
# this script only does the deterministic file edits, build, push, and pins.

set -euo pipefail

RHDH_CHECKOUT=""
BUILDER_REPO="quay.io/rhdh/plugin-catalog-builder-rhel10"
RUNNER_REPO="quay.io/rhdh/gitlab-runner"
STREAM=""
BUILDER_TAG=""
BUILDER_DIGEST=""
DATED_TAG=""
DO_PUSH=0
EXPIRES="150d"
declare -a CI_CHECKOUTS=()

usage() {
  cat <<EOF
Usage: $0 --rhdh /path/to/rhdh -b main|release-2.Y [OPTIONS]

Rebuild the gitlab-runner image for one RHDH stream and optionally re-pin
.gitlab-ci.yml files to the new dated tag.

Required:
  --rhdh PATH       rhdh checkout (holds build/containerfiles/gitlab-runner.Containerfile)
  -b, --branch SEL  stream branch: main or release-2.Y (rhdh and rhdh-plugin-catalog
                    must both have this branch checked out when --bump-ci is used)

Options:
  --builder-tag TAG  published builder tag to build from, e.g. 2.1-10;
                     default: resolve the mutable :X.Y tag (its newest X.Y-N)
  --builder-repo REPO builder image repository
                     (default: quay.io/rhdh/plugin-catalog-builder-rhel10;
                     rebuildGitlabRunner110.sh forces the rhel9 repo for 1.10)
  --version X.Y      RHDH stream version the runner tag uses (e.g. 2.1);
                     default: read version="X.Y" from the plugin-catalog
                     builder.Containerfile on the branch, when --catalog is given
  --catalog PATH     rhdh-plugin-catalog checkout, used to auto-detect --version
  --bump-ci PATH     rhdh-plugin-catalog and/or rhdh checkout(s) whose .gitlab-ci.yml
                     image: line should be re-pinned to the new dated tag; repeatable
  --push             push the built tags (default: build locally only)
  --expires D        quay.expires-after label (default: ${EXPIRES})
  --dry-run          print the operations without editing, building, or pushing
  -h, --help         this help

Output (always): builder tag+digest used, dated runner tag, and every file
changed, one per line, prefixed kind|detail — suitable for the workflow's
report step.
EOF
}

die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
log() { printf '[INFO] %s\n' "$*"; }
out() { printf '%s\n' "$*"; }

while [[ $# -gt 0 ]]; do
  case $1 in
    '--rhdh') RHDH_CHECKOUT="$2"; shift 1;;
    '-b'|'--branch') STREAM="$2"; shift 1;;
    '--builder-tag') BUILDER_TAG="$2"; shift 1;;
    '--builder-repo') BUILDER_REPO="$2"; shift 1;;
    '--version') STREAM_VERSION="$2"; shift 1;;
    '--catalog') CATALOG_CHECKOUT="$2"; shift 1;;
    '--bump-ci') CI_CHECKOUTS+=("$2"); shift 1;;
    '--push') DO_PUSH=1;;
    '--expires') EXPIRES="$2"; shift 1;;
    '--dry-run') DRYRUN=1;;
    '-h'|'--help') usage; exit 0;;
    *) usage; die "unknown parameter: $1";;
  esac
  shift 1
done

[[ -n "$RHDH_CHECKOUT" ]] || { usage; die "--rhdh is required"; }
[[ -n "$STREAM" ]] || { usage; die "-b main|release-2.Y is required"; }
[[ -d "$RHDH_CHECKOUT/build/containerfiles" ]] || die "not an rhdh checkout: $RHDH_CHECKOUT"
CONTAINERFILE="$RHDH_CHECKOUT/build/containerfiles/gitlab-runner.Containerfile"
[[ -f "$CONTAINERFILE" ]] || die "missing $CONTAINERFILE"

command -v skopeo >/dev/null 2>&1 || die "skopeo is required"
command -v podman >/dev/null 2>&1 || die "podman is required"

# Resolve the stream version (X.Y) used in runner tags.
if [[ -z "${STREAM_VERSION:-}" ]]; then
  if [[ -n "${CATALOG_CHECKOUT:-}" ]]; then
    # LABEL-block version="X.Y" (ENV lines like oras_version= must not match)
    STREAM_VERSION=$(grep -E '^[[:space:]]*version="[0-9]+\.[0-9]+"' \
      "${CATALOG_CHECKOUT}/build/containerfiles/builder.Containerfile" \
      | sed -E 's/.*version="([0-9]+\.[0-9]+)".*/\1/')
  fi
fi
[[ -n "${STREAM_VERSION:-}" ]] || die "cannot resolve stream version; pass --version X.Y (e.g. 2.1)"

# Guard: every checkout must be on the stream branch so edits land in the right place.
for co in "$RHDH_CHECKOUT" "${CATALOG_CHECKOUT:-}"; do
  [[ -d "$co" ]] || continue
  branch=$(git -C "$co" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
  [[ "$branch" == "$STREAM" ]] || die "$co is on branch '$branch', not '$STREAM'; check out the stream branch first"
done
for co in "${CI_CHECKOUTS[@]}"; do
  [[ -d "$co" ]] || continue
  branch=$(git -C "$co" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
  [[ "$branch" == "$STREAM" ]] || die "$co is on branch '$branch', not '$STREAM'; check out the stream branch first"
done

# Resolve the builder tag and digest.
if [[ -z "$BUILDER_TAG" ]]; then
  BUILDER_TAG=$(skopeo list-tags "docker://${BUILDER_REPO}" 2>/dev/null \
    | jq -r '.Tags[]' | grep -E "^${STREAM_VERSION//./\\.}-[0-9]+$" | sort -V | tail -1)
  [[ -n "$BUILDER_TAG" ]] || die "no published ${STREAM_VERSION}-N builder tag found in ${BUILDER_REPO}"
fi
BUILDER_DIGEST=$(skopeo inspect "docker://${BUILDER_REPO}:${BUILDER_TAG}" 2>/dev/null | jq -r '.Digest')
[[ "$BUILDER_DIGEST" == sha256:* ]] || die "could not resolve digest for ${BUILDER_REPO}:${BUILDER_TAG}"
log "builder = ${BUILDER_REPO}:${BUILDER_TAG}@${BUILDER_DIGEST}"

DATED_TAG="${STREAM_VERSION}-$(date +%Y%m%d-%H%M)"
log "runner tags = ${RUNNER_REPO}:${DATED_TAG}, :${STREAM_VERSION}-yarn4-node24, :${STREAM_VERSION}"

# Pin the runner Containerfile FROM to the immutable builder ref.
NEW_FROM="FROM ${BUILDER_REPO}:${BUILDER_TAG}@${BUILDER_DIGEST}"
if [[ -n "${DRYRUN:-}" ]]; then
  out "pin|${CONTAINERFILE}|${NEW_FROM}"
else
  sed -i "1s|^FROM .*|${NEW_FROM}|" "$CONTAINERFILE"
  [[ "$(head -1 "$CONTAINERFILE")" == "$NEW_FROM" ]] || die "failed to rewrite FROM in $CONTAINERFILE"
  out "pin|${CONTAINERFILE}|${NEW_FROM}"
fi

# Build the image.
cd "$RHDH_CHECKOUT/build/containerfiles" || die "cd failed"
if [[ -n "${DRYRUN:-}" ]]; then
  out "build|podman build . --no-cache -f gitlab-runner.Containerfile --label quay.expires-after=${EXPIRES} -t ${RUNNER_REPO}:${DATED_TAG} -t ${RUNNER_REPO}:${STREAM_VERSION}-yarn4-node24 -t ${RUNNER_REPO}:${STREAM_VERSION}"
else
  log "building (this takes a few minutes)..."
  podman build . --no-cache -f gitlab-runner.Containerfile \
    --label "quay.expires-after=${EXPIRES}" \
    -t "${RUNNER_REPO}:${DATED_TAG}" \
    -t "${RUNNER_REPO}:${STREAM_VERSION}-yarn4-node24" \
    -t "${RUNNER_REPO}:${STREAM_VERSION}" >/dev/null
  out "build|${RUNNER_REPO}:${DATED_TAG}"
fi

if [[ $DO_PUSH -eq 1 ]]; then
  for t in "$DATED_TAG" "${STREAM_VERSION}-yarn4-node24" "$STREAM_VERSION"; do
    if [[ -n "${DRYRUN:-}" ]]; then
      out "push|${RUNNER_REPO}:${t}"
    else
      podman push "${RUNNER_REPO}:${t}" >/dev/null
      out "push|${RUNNER_REPO}:${t}"
    fi
  done
else
  log "not pushing (pass --push to publish)"
fi

# Re-pin .gitlab-ci.yml in the named checkouts.
for co in "${CI_CHECKOUTS[@]}"; do
  ci="$co/.gitlab-ci.yml"
  [[ -f "$ci" ]] || die "no .gitlab-ci.yml in $co"
  if grep -q "image: ${RUNNER_REPO}:${STREAM_VERSION}$" "$ci"; then
    if [[ -n "${DRYRUN:-}" ]]; then
      out "ci|${ci}|${RUNNER_REPO}:${STREAM_VERSION} -> ${RUNNER_REPO}:${DATED_TAG}"
    else
      sed -i "s|image: ${RUNNER_REPO}:${STREAM_VERSION}$|image: ${RUNNER_REPO}:${DATED_TAG}|" "$ci"
      grep -q "image: ${RUNNER_REPO}:${DATED_TAG}" "$ci" || die "failed to re-pin $ci"
      out "ci|${ci}|${RUNNER_REPO}:${DATED_TAG}"
    fi
  else
    out "ci|${ci}|SKIPPED (no image: ${RUNNER_REPO}:${STREAM_VERSION} line; check manually)"
  fi
done

log "done. dated tag: ${DATED_TAG}"
out "summary|builder=${BUILDER_TAG}@${BUILDER_DIGEST}|runner=${DATED_TAG}"
