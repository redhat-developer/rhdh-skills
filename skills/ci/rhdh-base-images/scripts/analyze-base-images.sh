#!/usr/bin/env bash
# Analyze Containerfile/Dockerfile base images: current FROM lines, latest RHEC tags, UBI mismatches.
# Invoked by base-images-and-rpms.sh --analyze or run directly.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

RHDH_BUILD_SCRIPTS="${RHDH_BUILD_SCRIPTS:-}"
WORKDIRS=()
FILES=()
FIND_NAMES=(Containerfile Dockerfile)

usage() {
	local code="${1:-1}"
	echo "Usage: $0 [-s SCRIPTS_DIR] [-w WORKDIR]... [file ...]"
	echo "  -s  Directory with getLatestImageTags.sh (default: \$RHDH_BUILD_SCRIPTS)"
	echo "  -w  Repo root to scan (repeatable). Default: \$RHDH_REPO and \$RHDH_OPERATOR_REPO."
	echo "  With no file args, scans Containerfile and Dockerfile under each -w (maxdepth 5)."
	exit "$code"
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		-s) RHDH_BUILD_SCRIPTS="${2%/}"; shift 2 ;;
		-w) WORKDIRS+=("${2%/}"); shift 2 ;;
		-h|--help) usage 0 ;;
		-*) echo "Unknown option: $1" >&2; usage ;;
		*) FILES+=("$1"); shift ;;
	esac
done

if [[ ${#WORKDIRS[@]} -eq 0 ]]; then
	if [[ -z "${RHDH_REPO:-}" ]] || [[ -z "${RHDH_OPERATOR_REPO:-}" ]]; then
		echo "Set RHDH_REPO and RHDH_OPERATOR_REPO, or pass -w WORKDIR (repeatable)." >&2
		exit 1
	fi
	WORKDIRS=("$RHDH_REPO" "$RHDH_OPERATOR_REPO")
fi

if [[ -z "$RHDH_BUILD_SCRIPTS" ]]; then
	echo "Set RHDH_BUILD_SCRIPTS to '/path/to/rhidp/rhdh/build/scripts' directory, or pass -s SCRIPTS_DIR." >&2
	exit 1
fi

resolve_in_workdirs() {
	local f="$1"
	local w cf
	if [[ "$f" == /* ]] && [[ -f "$f" ]]; then
		echo "$f"
		return 0
	fi
	for w in "${WORKDIRS[@]}"; do
		cf="${w}/${f}"
		if [[ -f "$cf" ]]; then
			if command -v realpath >/dev/null 2>&1; then
				realpath "$cf" 2>/dev/null || echo "$cf"
			else
				echo "$cf"
			fi
			return 0
		fi
	done
	echo ""
	return 1
}

display_path() {
	local f="$1"
	local w
	for w in "${WORKDIRS[@]}"; do
		if [[ "$f" == "${w}/"* ]]; then
			echo "${w##*/}/${f#"${w}/"}"
			return
		fi
	done
	echo "$f"
}

canonical_path() {
	local p="$1"
	if command -v realpath >/dev/null 2>&1; then
		realpath "$p" 2>/dev/null || echo "$p"
	else
		echo "$p"
	fi
}

is_rhdh_repo() {
	local w="$1"
	if [[ -n "${RHDH_REPO:-}" ]] && [[ "$(canonical_path "$w")" == "$(canonical_path "$RHDH_REPO")" ]]; then
		return 0
	fi
	[[ -f "${w}/rpms.in.yaml" && -f "${w}/package.json" ]]
}

is_rhdh_excluded_path() {
	local f="$1"
	[[ "$f" == *"/e2e-tests/"* || "$f" == *"/.ci/"* ]]
}

command -v skopeo >/dev/null 2>&1 || { echo "skopeo required" >&2; exit 1; }

GLIT="${RHDH_BUILD_SCRIPTS}/getLatestImageTags.sh"
UPDATE="${RHDH_BUILD_SCRIPTS}/updateBaseImages.sh"

# Match updateBaseImages.sh: x.y-timestamp or x.y.z-timestamp (not bare timestamps like 1780432632).
RHEC_TAG_VERSION_PREFIX='[0-9]+\.[0-9]+(\.[0-9]+)?-'

is_well_formed_rhec_tag() {
	[[ "$1" =~ ^${RHEC_TAG_VERSION_PREFIX}[0-9]+$ ]]
}

parse_latest_well_formed_tag() {
	local raw="$1"
	local tag
	tag=$(printf '%s\n' "$raw" | sed -n 's#.*:\([^@[:space:]]*\)$#\1#p' \
		| grep -E "^${RHEC_TAG_VERSION_PREFIX}[0-9]+" | sort -V | tail -1)
	printf '%s' "$tag"
}

resolve_glit_tag() {
	local comment_url="${1:-}"
	if [[ -n "$comment_url" ]] && [[ "$comment_url" == *"#"* ]]; then
		printf '%s' "${comment_url#*#}"
	else
		printf '%s' "${RHEC_TAG_VERSION_PREFIX}"
	fi
}

if [[ ! -x "$GLIT" ]]; then
	echo "getLatestImageTags.sh not found at ${GLIT}" >&2
	echo "Set RHDH_BUILD_SCRIPTS to '/path/to/rhidp/rhdh/build/scripts' directory, or pass -s SCRIPTS_DIR." >&2
	exit 1
fi

for w in "${WORKDIRS[@]}"; do
	[[ -d "$w" ]] || { echo "Repo not found: ${w}" >&2; exit 1; }
done

if [[ ${#FILES[@]} -eq 0 ]]; then
	for w in "${WORKDIRS[@]}"; do
		find_prune=( ! -path '*/.git/*' ! -path '*/node_modules/*' )
		if is_rhdh_repo "$w"; then
			find_prune+=( ! -path '*/e2e-tests/*' ! -path '*/.ci/*' )
		fi
		for name in "${FIND_NAMES[@]}"; do
			while IFS= read -r f; do
				FILES+=("$f")
			done < <(find "${w}" -maxdepth 5 -name "${name}" \
				"${find_prune[@]}" 2>/dev/null | sort)
		done
	done
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
	echo "No Containerfiles or Dockerfiles found under: ${WORKDIRS[*]}"
	exit 1
fi

RESOLVED_FILES=()
for f in "${FILES[@]}"; do
	cf=$(resolve_in_workdirs "$f" || true)
	if [[ -n "$cf" ]] && [[ -f "$cf" ]]; then
		skip=0
		for w in "${WORKDIRS[@]}"; do
			if [[ "$cf" == "${w}/"* ]] && is_rhdh_repo "$w" && is_rhdh_excluded_path "$cf"; then
				echo "Skip (rhdh exclude e2e-tests/.ci): $(display_path "$cf")" >&2
				skip=1
				break
			fi
		done
		[[ "$skip" -eq 1 ]] && continue
		RESOLVED_FILES+=("$cf")
	else
		echo "Skip (not found): $f" >&2
	fi
done
if [[ ${#RESOLVED_FILES[@]} -eq 0 ]]; then
	echo "No readable container build files after resolving paths." >&2
	exit 1
fi
FILES=("${RESOLVED_FILES[@]}")

echo "=== Red Hat base image analysis ==="
echo "Scripts: ${RHDH_BUILD_SCRIPTS}"
echo "Repos:   ${WORKDIRS[*]}"
echo ""

for cf in "${FILES[@]}"; do
	echo "## $(display_path "$cf")"
	last_comment=""
	while IFS= read -r line || [[ -n "$line" ]]; do
		if [[ "$line" =~ ^[[:space:]]*#[[:space:]]*(https?://[^[:space:]#]+) ]]; then
			last_comment="${BASH_REMATCH[1]}"
			continue
		fi
		[[ "$line" =~ ^[[:space:]]*FROM[[:space:]]+([^[:space:]]+) ]] || continue
		ref="${BASH_REMATCH[1]}"
		[[ "$ref" == *":"* ]] || continue

		image_path="${ref%%@*}"
		image_path="${image_path#registry.access.redhat.com/}"
		image_path="${image_path#registry.redhat.io/}"
		image_name="${image_path%%:*}"
		current_tag="${image_path#*:}"

		echo "  FROM ${image_name}"
		echo "    comment: ${last_comment:-"(none — add # https://registry.../image above FROM)"}"
		echo "    current: ${current_tag}"
		if ! is_well_formed_rhec_tag "$current_tag"; then
			echo "    warning: current tag is not well-formed x.y-z or x.y.z-z (updateBaseImages.sh will skip)"
		fi

		glit_tag=$(resolve_glit_tag "$last_comment")
		latest_raw=$("$GLIT" -q -c "${image_name}" --tag "${glit_tag}" --latestNext latest 2>/dev/null || true)
		latest_tag=$(parse_latest_well_formed_tag "$latest_raw")

		if [[ -n "$latest_tag" ]]; then
			echo "    latest:  ${latest_tag}"
		elif [[ -n "$latest_raw" ]]; then
			echo "    latest:  (no well-formed x.y-z or x.y.z-z tag; filter: ${glit_tag})"
		else
			echo "    latest:  (query failed — check registry login)"
		fi

		if [[ -z "$latest_tag" ]]; then
			echo "    status:  SKIPPED (no well-formed tag — update script would skip)"
		elif ! is_well_formed_rhec_tag "$current_tag"; then
			echo "    status:  SKIPPED (malformed current tag — fix before update)"
		elif [[ "$current_tag" != "$latest_tag" ]] \
			&& [[ "$(printf '%s\n' "${current_tag}" "${latest_tag}" | sort -V | tail -1)" == "${latest_tag}" ]]; then
			echo "    status:  UPDATE AVAILABLE"
		else
			echo "    status:  ok"
		fi
		echo ""
		last_comment=""
	done < "$cf"

	ubi_versions=()
	while IFS= read -r fromline; do
		[[ "$fromline" =~ ^[[:space:]]*FROM[[:space:]]+([^[:space:]]+) ]] || continue
		ref="${BASH_REMATCH[1]}"
		[[ "$ref" =~ ubi(9|10) ]] || continue
		tag="${ref%%@*}"; tag="${tag##*:}"
		[[ "$tag" =~ ^([0-9]+\.[0-9]+) ]] && ubi_versions+=("${BASH_REMATCH[1]}")
	done < <(grep -iE '^[[:space:]]*FROM[[:space:]]+' "$cf" || true)
	if [[ ${#ubi_versions[@]} -ge 2 ]]; then
		unique=$(printf '%s\n' "${ubi_versions[@]}" | sort -u)
		if [[ $(echo "$unique" | wc -l | tr -d ' ') -gt 1 ]]; then
			echo "  UBI WARNING: multiple minor versions in same file: $(echo "$unique" | tr '\n' ' ')"
		fi
	fi
	echo ""
done

if [[ -x "$UPDATE" ]]; then
	for w in "${WORKDIRS[@]}"; do
		echo "Run update: ${UPDATE} -w \"${w}\" -f \"Containerfile Dockerfile\" -maxdepth 5 --pr"
	done
else
	echo "Run update: ${RHDH_BUILD_SCRIPTS}/updateBaseImages.sh -w <repo> -f \"Containerfile Dockerfile\" -maxdepth 5 --pr"
fi
