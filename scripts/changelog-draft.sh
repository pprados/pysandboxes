#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Called by tag-release.sh for a final version. Usage: changelog-draft.sh <last final tag, or empty for all history>
# Prints the body of the CHANGELOG.md entry: Keep a Changelog sections written for users. The conventional commit
# types choose what counts (feat, fix, perf, security); an LLM only rewrites the subjects, without detail. Its output
# is checked for that shape, and anything else, a failure or no LLM falls back to the subjects themselves: a release
# never depends on a model. The maintainer edits and approves the result before it is committed.
set -euo pipefail

since=${1:-}
types='^(feat|fix|perf|security)(\([^)]*\))?!?: '
subjects=$(git log --no-merges --format=%s ${since:+"$since..HEAD"} | grep -E "$types" || true)
[[ -n $subjects ]] || exit 0

prompt="Rewrite these git commit subjects as the changelog of a release, for users of the library. Output only \
Keep a Changelog sections among '### Added', '### Changed', '### Fixed', '### Security', each followed by one short \
bullet ('- ') per user-visible change, merging duplicates. feat is Added or Changed, fix is Fixed, perf is Changed. \
No technical detail, no file or function names, no version line, no code fence, no other text."
if [[ -n ${CHANGELOG_LLM:-} ]]; then
    read -r -a llm <<<"$CHANGELOG_LLM"
else
    llm=(claude -p --tools "" --no-session-persistence --strict-mcp-config --setting-sources "")
fi

shape='^(### (Added|Changed|Deprecated|Removed|Fixed|Security)|- .+|  .+|)$'
errors=$(mktemp)
trap 'rm -f "$errors"' EXIT
if draft=$("${llm[@]}" "$prompt" <<<"$subjects" 2>"$errors") &&
    grep -q '^- ' <<<"$draft" && ! grep -qvE "$shape" <<<"$draft"; then
    printf '%s\n' "$draft"
    exit 0
fi

echo "changelog-draft: the LLM gave no usable draft, falls back to the commit subjects" >&2
tail -n 3 "$errors" | sed 's/^/  /' >&2
[[ -z ${draft:-} ]] || head -n 3 <<<"$draft" | sed 's/^/  output: /' >&2
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
