#!/usr/bin/env bash
# Pre-compact hook for the OpenSpec journal.
#
# Emits a `context.compacted` event into the journal of the most recently
# active OpenSpec change, if one exists. Stays silent (exit 0) when there
# is nothing to log so it does not block compaction.
#
# Claude Code wires this as a `PreCompact` hook. Other agent clients can
# call the same script from an equivalent lifecycle hook; set
# OPEN_SPEC_JOURNAL_AGENT to label the emitted event, for example:
#
#   OPEN_SPEC_JOURNAL_AGENT=Codex /abs/path/to/scripts/openspec-journal-precompact-hook.sh
#
# Wire via `~/.claude/settings.json` or `.claude/settings.json`:
#
#   {
#     "hooks": {
#       "PreCompact": [
#         {"hooks": [{"type": "command",
#           "command": "/abs/path/to/scripts/openspec-journal-precompact-hook.sh"
#         }]}
#       ]
#     }
#   }
#
# The script is intentionally tolerant: any failure (no repo, no active
# change, journal helper missing) is silently ignored so compaction is
# never blocked by journaling.

set -u

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "${repo_root}" ] || exit 0

# The helper ships beside this hook in the skill directory, not under the
# product repo's scripts/. Resolve it relative to this script.
helper="$(dirname "$0")/openspec-journal.py"
changes_dir="${repo_root}/openspec/changes"
agent="${OPEN_SPEC_JOURNAL_AGENT:-Claude Code}"
[ -f "${helper}" ] && [ -d "${changes_dir}" ] || exit 0

# Portable mtime in epoch seconds: BSD stat -f, GNU stat -c.
mtime() { stat -f '%m' "$1" 2>/dev/null || stat -c '%Y' "$1" 2>/dev/null; }

# Pick the most recently modified non-archive journal. find only discovers
# paths (portable); mtime() ranks them, avoiding non-portable stat in find.
journal=""
latest=0
while IFS= read -r candidate; do
    [ -n "${candidate}" ] || continue
    m=$(mtime "${candidate}")
    case "${m}" in ''|*[!0-9]*) continue ;; esac
    if [ "${m}" -gt "${latest}" ]; then
        latest="${m}"
        journal="${candidate}"
    fi
done <<EOF
$(find "${changes_dir}" -mindepth 2 -maxdepth 3 -name journal.jsonl \
    -not -path "*/archive/*" 2>/dev/null)
EOF

[ -n "${journal}" ] || exit 0

# Only journal compactions for changes touched in the last 6 hours; older
# trails belong to changes the user has likely moved on from.
now=$(date +%s 2>/dev/null || true)
case "${now}" in ''|*[!0-9]*) exit 0 ;; esac
if [ "$((now - latest))" -gt 21600 ]; then
    exit 0
fi

change=$(basename "$(dirname "${journal}")")

python3 "${helper}" "${change}" context.compacted \
    input="${agent} PreCompact hook fired during ${change}." \
    output="Context compaction observed; chat continuation may follow." \
    >/dev/null 2>&1 || true

exit 0
