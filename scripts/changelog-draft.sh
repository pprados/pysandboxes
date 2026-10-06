#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Called by tag-release.sh for a final version.
# Usage: changelog-draft.sh <last final tag, or empty for all history> [file holding the open entry's lines]
# Prints the new body of the CHANGELOG.md entry: Keep a Changelog sections written for users, synthesised by an LLM
# from the lines the entry already holds (the maintainer's notes, the lines merges added) and the commits since the
# tag. The conventional commit types choose which commits count (feat, fix, perf, security). The output is checked for
# that shape; anything else, a failure or no LLM falls back to the entry's lines followed by the commit subjects: a
# release never depends on a model. Prints nothing when no commit counts. The maintainer edits and approves the
# result before it is committed.
set -euo pipefail

since=${1:-}
entry=$([[ -n ${2:-} ]] && sed -e '/./,$!d' "$2" || true)
types='^(feat|fix|perf|security)(\([^)]*\))?!?: '
subjects=$(git log --no-merges --format=%s ${since:+"$since..HEAD"} | grep -E "$types" || true)
[[ -n $subjects ]] || exit 0

prompt="Write the changelog of a release, for users of the library, from the current entry and the git commit \
subjects below. Keep every user-visible point of the current entry, its wording when it is already good, and add the \
changes the commits bring, merging duplicates. Output only Keep a Changelog sections among '### Added', \
'### Changed', '### Fixed', '### Security', each followed by one short bullet ('- ') per change. feat is Added or \
Changed, fix is Fixed, perf is Changed. No technical detail, no file or function names, no version line, no code \
fence, no other text."
input=$(printf 'Current entry:\n%s\n\nCommit subjects:\n%s\n' "${entry:-(empty)}" "$subjects")
if [[ -n ${CHANGELOG_LLM:-} ]]; then
    read -r -a llm <<<"$CHANGELOG_LLM"
else
    llm=(claude -p --tools "" --no-session-persistence --strict-mcp-config --setting-sources "")
fi

shape='^(### (Added|Changed|Deprecated|Removed|Fixed|Security)|- .+|  .+|)$'
errors=$(mktemp)
trap 'rm -f "$errors"' EXIT
if draft=$("${llm[@]}" "$prompt" <<<"$input" 2>"$errors") &&
    grep -q '^- ' <<<"$draft" && ! grep -qvE "$shape" <<<"$draft"; then
    printf '%s\n' "$draft"
    exit 0
fi

echo "changelog-draft: the LLM gave no usable draft, falls back to the entry and the commit subjects" >&2
tail -n 3 "$errors" | sed 's/^/  /' >&2
[[ -z ${draft:-} ]] || head -n 3 <<<"$draft" | sed 's/^/  output: /' >&2
[[ -z $entry ]] || { printf '%s\n' "$entry"; printed=1; }
section() {
    local lines
    lines=$(grep -E "^($2)(\([^)]*\))?!?: " <<<"$subjects" | sed -E 's/^[a-z]+(\([^)]*\))?!?: //; s/^./\U&/' || true)
    [[ -z $lines ]] && return
    [[ -n ${printed:-} ]] && echo
    echo "### $1"
    sed 's/^/- /' <<<"$lines"
    printed=1
}
section Added feat
section Changed perf
section Fixed fix
section Security security
