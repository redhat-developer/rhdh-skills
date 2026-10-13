#!/usr/bin/env bash
#
# Check (and optionally rewrite) Konflux task bundle pins against
# quay.io/konflux-ci/tekton-catalog/data-acceptable-bundles:latest.
#
# Keep in sync with rhdh-plugin-catalog build/scripts/checkTrustedTasks.sh.
#
# Requires: bash, jq >= 1.7, skopeo (unless --data-file). yq is only needed when
# --data-file is YAML rather than JSON.
#
set -euo pipefail

SCRIPT_NAME=$(basename "$0")
DEFAULT_DATA_SOURCE='quay.io/konflux-ci/tekton-catalog/data-acceptable-bundles:latest'
DEFAULT_HORIZON_DAYS=14

DATA_SOURCE="$DEFAULT_DATA_SOURCE"
DATA_FILE=""
HORIZON_DAYS="$DEFAULT_HORIZON_DAYS"
NOW_ISO=""
APPLY=0
JSON_OUT=0
STRICT=0
PRINT_DIGEST=""
PRINT_LATEST_TAG=""
WRITE_DATA=""
declare -a SCAN_PATHS=()

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [options] [file-or-dir ...]

Check Tekton YAML for quay.io/konflux-ci/tekton-catalog/task-*:tag@sha256 pins
against the Konflux trusted-task list. Expiry uses a 14-day horizon so a pin
that ECP still accepts today but that expires within two weeks is treated as
needing a replacement.

Options:
  -h, --help                  Show this help
  --data-file PATH            Trusted-task YAML or JSON (skip skopeo)
  --data-source IMAGE         OCI image (default: $DEFAULT_DATA_SOURCE)
  --horizon-days N            Days of buffer (default: $DEFAULT_HORIZON_DAYS)
  --now TIMESTAMP             Freeze "now" as UTC ISO-8601 (tests)
  --json                      JSON object on stdout (warnings still on stderr)
  --strict                    Also fail on stale (not the current record)
  --apply-trusted-digests     Rewrite same-tag SHA to the latest usable digest
  --print-digest IMAGE:TAG    Print sha256:... for a usable-with-buffer pin
  --print-latest-tag IMAGE    Print highest dotted tag with a usable digest
  --write-data PATH           Fetch/parse the allow-list and write JSON, then exit
                              unless other actions are requested
  --scan-dir DIR              Extra directory to scan (repeatable)

Positional paths default to .tekton and .tekton-templates when those exist.

Exit codes:
  0  all pins trusted/stale, or only expiring-no-successor warnings
  1  expired / untrusted / expired-no-successor (or stale with --strict)
  2  usage or tooling error
EOF
}

log_err() { printf '%s\n' "$*" >&2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --data-file) DATA_FILE="${2:-}"; shift 2 ;;
    --data-source) DATA_SOURCE="${2:-}"; shift 2 ;;
    --horizon-days) HORIZON_DAYS="${2:-}"; shift 2 ;;
    --now) NOW_ISO="${2:-}"; shift 2 ;;
    --json) JSON_OUT=1; shift ;;
    --strict) STRICT=1; shift ;;
    --apply-trusted-digests) APPLY=1; shift ;;
    --print-digest) PRINT_DIGEST="${2:-}"; shift 2 ;;
    --print-latest-tag) PRINT_LATEST_TAG="${2:-}"; shift 2 ;;
    --write-data) WRITE_DATA="${2:-}"; shift 2 ;;
    --scan-dir) SCAN_PATHS+=("${2:-}"); shift 2 ;;
    --) shift; break ;;
    -*)
      log_err "Unknown option: $1"
      usage >&2
      exit 2
      ;;
    *) SCAN_PATHS+=("$1"); shift ;;
  esac
done
while [[ $# -gt 0 ]]; do
  SCAN_PATHS+=("$1")
  shift
done

if ! command -v jq >/dev/null 2>&1; then
  log_err "jq is required (jq >= 1.7)"
  exit 2
fi

if ! [[ "$HORIZON_DAYS" =~ ^[0-9]+$ ]]; then
  log_err "--horizon-days must be a non-negative integer"
  exit 2
fi

to_epoch() {
  local iso="$1"
  local epoch=""
  iso="${iso%Z}"
  iso="${iso%%.*}"
  if epoch=$(date -u -d "${iso}Z" +%s 2>/dev/null); then
    printf '%s' "$epoch"
    return 0
  fi
  if epoch=$(date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "${iso}Z" +%s 2>/dev/null); then
    printf '%s' "$epoch"
    return 0
  fi
  return 1
}

from_epoch() {
  date -u -d "@$1" +'%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
    || date -u -r "$1" +'%Y-%m-%dT%H:%M:%SZ'
}

NOW_EPOCH=""
if [[ -n "$NOW_ISO" ]]; then
  NOW_EPOCH=$(to_epoch "$NOW_ISO") || {
    log_err "Could not parse --now: $NOW_ISO"
    exit 2
  }
else
  NOW_EPOCH=$(date -u +%s)
  NOW_ISO=$(from_epoch "$NOW_EPOCH")
fi
CUTOFF_EPOCH=$((NOW_EPOCH + HORIZON_DAYS * 86400))
CUTOFF_ISO=$(from_epoch "$CUTOFF_EPOCH")

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT
TRUSTED_JSON="$WORKDIR/trusted_tasks.json"

yaml_or_json_to_json() {
  local src="$1" dest="$2"
  local first
  first=$(tr -d ' \t\r' <"$src" | head -1 || true)
  if [[ "$first" == '{' || "$first" == '[' ]]; then
    jq -c '.' "$src" >"$dest"
    return
  fi
  if ! command -v yq >/dev/null 2>&1; then
    log_err "yq is required to parse YAML --data-file (or pass JSON)"
    exit 2
  fi
  if yq --version 2>&1 | grep -qi mikefarah; then
    yq -o=json '.' "$src" >"$dest"
  else
    yq -c '.' "$src" >"$dest"
  fi
}

fetch_trusted_yaml() {
  local dest="$1"
  local tmp digest
  if ! command -v skopeo >/dev/null 2>&1; then
    log_err "skopeo is required unless --data-file is set"
    exit 2
  fi
  tmp=$(mktemp -d)
  skopeo copy --quiet "docker://${DATA_SOURCE}" "dir:${tmp}"
  digest=$(jq -r '
    .layers
    | map(select((.annotations["org.opencontainers.image.title"] // "") | test("trusted_tekton_tasks")))
    | .[0].digest // empty
  ' "${tmp}/manifest.json")
  if [[ -z "$digest" ]]; then
    digest=$(jq -r '.layers | max_by(.size // 0) | .digest' "${tmp}/manifest.json")
  fi
  digest="${digest#sha256:}"
  if [[ ! -f "${tmp}/${digest}" ]]; then
    log_err "Could not find trusted_tekton_tasks layer in ${DATA_SOURCE}"
    rm -rf "$tmp"
    exit 2
  fi
  cp "${tmp}/${digest}" "$dest"
  rm -rf "$tmp"
}

load_trusted_data() {
  local raw="$WORKDIR/trusted_raw"
  if [[ -n "$DATA_FILE" ]]; then
    if [[ ! -f "$DATA_FILE" ]]; then
      log_err "data file not found: $DATA_FILE"
      exit 2
    fi
    yaml_or_json_to_json "$DATA_FILE" "$raw"
  else
    fetch_trusted_yaml "$WORKDIR/trusted.yml"
    yaml_or_json_to_json "$WORKDIR/trusted.yml" "$raw"
  fi
  jq -c '.trusted_tasks // .' "$raw" >"$TRUSTED_JSON"
}

norm_digest() {
  local d="$1"
  d="${d#sha256:}"
  printf 'sha256:%s' "$d"
}

is_dotted_tag() {
  [[ "$1" =~ ^[0-9]+(\.[0-9]+)*$ ]]
}

is_newer_version() {
  local current="$1" candidate="$2"
  [[ "$current" != "$candidate" ]] \
    && [[ "$(printf '%s\n%s\n' "$current" "$candidate" | sort -V | tail -1)" == "$candidate" ]]
}

oci_key() {
  local image="$1" tag="$2"
  printf 'oci://%s:%s' "$image" "$tag"
}

records_for_key() {
  jq -c --arg k "$1" '.[$k] // []' "$TRUSTED_JSON"
}

record_expires() {
  jq -r --arg d "$2" '
    .[] | select((.ref | sub("^sha256:";"")) == ($d | sub("^sha256:";"")))
    | .expires_on // empty
  ' <<<"$1" | head -1
}

usable_digest_for_key() {
  local key="$1"
  local records cutoff
  records=$(records_for_key "$key")
  cutoff="$CUTOFF_EPOCH"
  jq -r --argjson now "$NOW_EPOCH" --argjson cutoff "$cutoff" '
    def epoch(ts):
      if (ts == null or ts == "") then null
      else (ts | sub("\\.[0-9]+Z$"; "Z") | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) end;
    def usable:
      (epoch(.effective_on) as $e | ($e == null or $e <= $now))
      and (epoch(.expires_on) as $x | ($x == null or $x > $cutoff));
    ([.[] | select(usable) | select((.expires_on // "") == "")] + [.[] | select(usable)])
    | (.[0].ref // empty)
  ' <<<"$records"
}

newest_usable_tag() {
  local image="$1"
  local prefix key tag best=""
  prefix=$(printf 'oci://%s:' "$image")
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    tag="${key#"$prefix"}"
    is_dotted_tag "$tag" || continue
    if [[ -z "$(usable_digest_for_key "$key")" ]]; then
      continue
    fi
    if [[ -z "$best" ]] || is_newer_version "$best" "$tag"; then
      best="$tag"
    fi
  done < <(jq -r --arg p "$prefix" 'keys[] | select(startswith($p))' "$TRUSTED_JSON")
  printf '%s' "$best"
}

suggested_successor() {
  local image="$1" tag="$2" digest="$3"
  local key same newer_tag newer_key cand
  key=$(oci_key "$image" "$tag")
  same=$(usable_digest_for_key "$key")
  if [[ -n "$same" && "$(norm_digest "$same")" != "$(norm_digest "$digest")" ]]; then
    printf '%s:%s@%s' "$image" "$tag" "$(norm_digest "$same")"
    return 0
  fi
  newer_tag=$(newest_usable_tag "$image")
  if [[ -n "$newer_tag" ]] && is_newer_version "$tag" "$newer_tag"; then
    newer_key=$(oci_key "$image" "$newer_tag")
    cand=$(usable_digest_for_key "$newer_key")
    if [[ -n "$cand" ]]; then
      printf '%s:%s@%s' "$image" "$newer_tag" "$(norm_digest "$cand")"
      return 0
    fi
  fi
  return 1
}

parse_bundle() {
  local ref="$1"
  BUNDLE_IMAGE="${ref%%:*}"
  local rest="${ref#*:}"
  BUNDLE_TAG="${rest%%@*}"
  BUNDLE_DIGEST=$(norm_digest "${rest#*@}")
}

collect_yaml_files() {
  local p
  for p in "$@"; do
    if [[ -f "$p" ]]; then
      printf '%s\n' "$p"
    elif [[ -d "$p" ]]; then
      find "$p" \( -name '*.yaml' -o -name '*.yml' \) -type f
    fi
  done
}

extract_refs_from_file() {
  local file="$1"
  grep -E '^[[:space:]]+value:[[:space:]]+quay.io/konflux-ci/tekton-catalog/task-[^[:space:]"'\'']+:[0-9.]+@sha256:[a-fA-F0-9]+' "$file" \
    | sed -E 's/^[[:space:]]+value:[[:space:]]+//; s/["'\'']//g' \
    || true
}

warn_no_successor() {
  local task="$1" tag="$2" digest="$3" expires="$4"
  local pin="${task}:${tag}@${digest}"
  if [[ -n "$expires" ]]; then
    log_err "[WARN] ${pin} expires on ${expires} (horizon is ${HORIZON_DAYS} days)."
  else
    log_err "[WARN] ${pin} is not in data-acceptable-bundles (horizon is ${HORIZON_DAYS} days)."
  fi
  log_err "No newer trusted tag/digest is in data-acceptable-bundles yet."
  log_err "Re-run this check in a few days after Konflux publishes a replacement."
  log_err "If none appears, ask in Slack #konflux-users."
}

classify_ref() {
  local ref="$1"
  parse_bundle "$ref"
  local image="$BUNDLE_IMAGE" tag="$BUNDLE_TAG" digest="$BUNDLE_DIGEST"
  local task="${image##*/}"
  local key records expires status suggested="" newer=""
  key=$(oci_key "$image" "$tag")
  records=$(records_for_key "$key")
  expires=$(record_expires "$records" "$digest")
  local in_list
  in_list=$(jq -r --arg d "$digest" '
    any(.[]; (.ref | sub("^sha256:";"")) == ($d | sub("^sha256:";"")))
  ' <<<"$records")

  local exp_epoch="" usable_buf=0 usable_now=0
  if [[ "$in_list" == "true" ]]; then
    if [[ -z "$expires" ]]; then
      usable_buf=1
      usable_now=1
    else
      exp_epoch=$(to_epoch "$expires" || true)
      if [[ -n "$exp_epoch" ]]; then
        if (( exp_epoch > CUTOFF_EPOCH )); then usable_buf=1; fi
        if (( exp_epoch > NOW_EPOCH )); then usable_now=1; fi
      fi
    fi
  fi

  suggested=$(suggested_successor "$image" "$tag" "$digest" || true)
  local newest
  newest=$(newest_usable_tag "$image")
  if [[ -n "$newest" ]] && is_newer_version "$tag" "$newest"; then
    local nk nd
    nk=$(oci_key "$image" "$newest")
    nd=$(usable_digest_for_key "$nk")
    if [[ -n "$nd" ]]; then
      newer="${image}:${newest}@$(norm_digest "$nd")"
    fi
  fi

  if [[ "$in_list" != "true" ]]; then
    if [[ -n "$suggested" ]]; then
      status="untrusted"
    else
      status="expired-no-successor"
    fi
  elif (( usable_buf == 1 )); then
    local current
    current=$(usable_digest_for_key "$key")
    if [[ -n "$current" && "$(norm_digest "$current")" != "$digest" ]]; then
      status="stale"
      suggested="${image}:${tag}@$(norm_digest "$current")"
    else
      status="trusted"
    fi
  elif (( usable_now == 0 )); then
    if [[ -n "$suggested" ]]; then
      status="expired"
    else
      status="expired-no-successor"
    fi
  else
    if [[ -n "$suggested" ]]; then
      status="expired"
    else
      status="expiring-no-successor"
    fi
  fi

  jq -nc \
    --arg ref "$ref" \
    --arg task "$task" \
    --arg tag "$tag" \
    --arg digest "$digest" \
    --arg status "$status" \
    --arg expires_on "$expires" \
    --arg suggested "$suggested" \
    --arg newer "$newer" \
    '{
      ref: $ref,
      task: $task,
      tag: $tag,
      digest: $digest,
      status: $status,
      expires_on: (if $expires_on == "" then null else $expires_on end),
      suggested: (if $suggested == "" then null else $suggested end),
      newer_tag: (if $newer == "" then null else $newer end)
    }'
}

load_trusted_data

if [[ -n "$WRITE_DATA" ]]; then
  cp "$TRUSTED_JSON" "$WRITE_DATA"
  if [[ -z "$PRINT_DIGEST" && -z "$PRINT_LATEST_TAG" && "$APPLY" -eq 0 && ${#SCAN_PATHS[@]} -eq 0 ]]; then
    exit 0
  fi
fi

if [[ -n "$PRINT_DIGEST" ]]; then
  parse_bundle "${PRINT_DIGEST%@*}@sha256:dummy"
  if [[ "$PRINT_DIGEST" == *@* ]]; then
    parse_bundle "$PRINT_DIGEST"
  else
    BUNDLE_IMAGE="${PRINT_DIGEST%%:*}"
    BUNDLE_TAG="${PRINT_DIGEST#*:}"
  fi
  key=$(oci_key "$BUNDLE_IMAGE" "$BUNDLE_TAG")
  digest=$(usable_digest_for_key "$key")
  if [[ -z "$digest" ]]; then
    log_err "No usable-with-buffer digest for ${BUNDLE_IMAGE}:${BUNDLE_TAG}"
    exit 1
  fi
  printf '%s\n' "$(norm_digest "$digest")"
  exit 0
fi

if [[ -n "$PRINT_LATEST_TAG" ]]; then
  image="$PRINT_LATEST_TAG"
  tag=$(newest_usable_tag "$image")
  if [[ -z "$tag" ]]; then
    log_err "No usable-with-buffer dotted tag for ${image}"
    exit 1
  fi
  printf '%s\n' "$tag"
  exit 0
fi

if [[ ${#SCAN_PATHS[@]} -eq 0 ]]; then
  [[ -d .tekton ]] && SCAN_PATHS+=(.tekton)
  [[ -d .tekton-templates ]] && SCAN_PATHS+=(.tekton-templates)
fi
if [[ ${#SCAN_PATHS[@]} -eq 0 ]]; then
  log_err "No scan paths. Pass files/dirs or run from a repo with .tekton/"
  exit 2
fi

declare -A REF_FILES=()
declare -a UNIQUE_REFS=()
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    if [[ -z "${REF_FILES[$ref]+x}" ]]; then
      UNIQUE_REFS+=("$ref")
      REF_FILES[$ref]="$file"
    else
      REF_FILES[$ref]="${REF_FILES[$ref]}"$'\n'"$file"
    fi
  done < <(extract_refs_from_file "$file")
done < <(collect_yaml_files "${SCAN_PATHS[@]}" | sort -u)

if [[ ${#UNIQUE_REFS[@]} -eq 0 ]]; then
  log_err "No konflux task bundle refs found in: ${SCAN_PATHS[*]}"
  if [[ "$JSON_OUT" -eq 1 ]]; then
    jq -nc --arg now "$NOW_ISO" --arg cutoff "$CUTOFF_ISO" --argjson horizon "$HORIZON_DAYS" \
      '{horizon_days:$horizon, now:$now, cutoff:$cutoff, results:[]}'
  fi
  exit 0
fi

RESULTS_JSON='[]'
FAIL=0
for ref in "${UNIQUE_REFS[@]}"; do
  item=$(classify_ref "$ref")
  files_json=$(printf '%s\n' "${REF_FILES[$ref]}" | sort -u | jq -Rsc 'split("\n") | map(select(length>0))')
  item=$(jq -c --argjson files "$files_json" '. + {files:$files}' <<<"$item")
  RESULTS_JSON=$(jq -nc --argjson r "$RESULTS_JSON" --argjson i "$item" '$r + [$i]')

  status=$(jq -r '.status' <<<"$item")
  task=$(jq -r '.task' <<<"$item")
  tag=$(jq -r '.tag' <<<"$item")
  digest=$(jq -r '.digest' <<<"$item")
  expires=$(jq -r '.expires_on // empty' <<<"$item")
  suggested=$(jq -r '.suggested // empty' <<<"$item")
  newer=$(jq -r '.newer_tag // empty' <<<"$item")

  line=$(printf '%-24s %s:%s@%s' "$status" "$task" "$tag" "$digest")
  if [[ -n "$suggested" && "$status" != "trusted" ]]; then
    line="${line}  -> ${suggested}"
  elif [[ -n "$newer" && "$status" == "trusted" ]]; then
    line="${line}  (newer tag available: ${newer})"
  fi
  if [[ "$JSON_OUT" -eq 0 ]]; then
    printf '%s\n' "$line"
  fi

  case "$status" in
    expired|untrusted|expired-no-successor) FAIL=1 ;;
    stale) [[ "$STRICT" -eq 1 ]] && FAIL=1 ;;
  esac
  if [[ "$status" == "expiring-no-successor" || "$status" == "expired-no-successor" ]]; then
    warn_no_successor "$task" "$tag" "$digest" "$expires"
  fi
done

if [[ "$APPLY" -eq 1 ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    old=$(jq -r '.ref' <<<"$row")
    suggested=$(jq -r '.suggested // empty' <<<"$row")
    status=$(jq -r '.status' <<<"$row")
    [[ -z "$suggested" ]] && continue
    parse_bundle "$old"
    old_tag="$BUNDLE_TAG"
    parse_bundle "$suggested"
    new_tag="$BUNDLE_TAG"
    [[ "$old_tag" == "$new_tag" ]] || continue
    [[ "$status" == "trusted" ]] && continue
    while IFS= read -r file; do
      [[ -z "$file" ]] && continue
      sed -i -r -e "s|${old}|${suggested}|g" "$file"
    done < <(jq -r '.files[]' <<<"$row")
    log_err "applied ${old} -> ${suggested}"
  done < <(jq -c '.[]' <<<"$RESULTS_JSON")
fi

if [[ "$JSON_OUT" -eq 1 ]]; then
  jq -nc \
    --arg now "$NOW_ISO" \
    --arg cutoff "$CUTOFF_ISO" \
    --argjson horizon "$HORIZON_DAYS" \
    --argjson results "$RESULTS_JSON" \
    '{horizon_days:$horizon, now:$now, cutoff:$cutoff, results:$results}'
fi

exit "$FAIL"
