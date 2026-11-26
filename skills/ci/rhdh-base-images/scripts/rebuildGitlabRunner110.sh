#!/usr/bin/env bash
#
# Copyright (c) 2026 Red Hat, Inc.
# This program and the accompanying materials are made
# available under the terms of the Eclipse Public License 2.0
# which is available at https://www.eclipse.org/legal/epl-2.0/
#
# SPDX-License-Identifier: EPL-2.0
#
# Rebuild quay.io/rhdh/gitlab-runner for the RHDH 1.10 stream ONLY, from the
# published plugin-catalog-builder-rhel9 image, and re-pin .gitlab-ci.yml.
#
# Thin wrapper over rebuildGitlabRunner.sh: forces the rhel9 builder repo, the
# rhdh-1.10-rhel-9 branch, and stream version 1.10. Every checkout must be on
# rhdh-1.10-rhel-9 (the wrapper rejects anything else, including 1.9).
#
# RETIREMENT: delete this script (and its workflow section) once RHDH 2.1 is
# EOL in March 2027 and the 1.10 stream is closed; rebuildGitlabRunner.sh
# covers every 2.y stream.

set -euo pipefail

DIR=$(cd "$(dirname "$0")" || exit 1; pwd)
MAIN="${DIR}/rebuildGitlabRunner.sh"
[[ -f "$MAIN" ]] || { printf '[ERROR] %s not found next to this script\n' "$MAIN" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $0 --rhdh /path/to/rhdh [OPTIONS]

Rebuild the gitlab-runner image for the RHDH 1.10 stream (rhdh-1.10-rhel-9
branch, quay.io/rhdh/plugin-catalog-builder-rhel9 builder) and optionally
re-pin .gitlab-ci.yml files to the new dated tag.

This is the 1.10-only variant of rebuildGitlabRunner.sh; it accepts the same
options EXCEPT -b/--branch, --version, and --builder-repo, which are pinned
here (rhdh-1.10-rhel-9, 1.10, and the rhel9 builder repo). 1.9 is not
supported. Delete this script once RHDH 2.1 is EOL (March 2027).

See: $MAIN --help
EOF
}

declare -a FORWARD=()
while [[ $# -gt 0 ]]; do
  case $1 in
    '-b'|'--branch'|'--version'|'--builder-repo')
      printf '[ERROR] %s is pinned to the 1.10 stream; do not pass %s\n' "$0" "$1" >&2
      exit 1;;
    '-h'|'--help') usage; exit 0;;
    *) FORWARD+=("$1");;
  esac
  shift 1
done

# shellcheck disable=SC2086
exec "$MAIN" \
  --builder-repo "quay.io/rhdh/plugin-catalog-builder-rhel9" \
  -b "rhdh-1.10-rhel-9" \
  --version "1.10" \
  "${FORWARD[@]}"
