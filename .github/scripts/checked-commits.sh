#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Jobs push-checks and reuse-lookup of release.yml. Usage: checked-commits.sh <commit sha>
# A final tag sits on a release commit that only dates CHANGELOG.md, and lint.yml and test.yml skip documentation
# (**.md, wiki/**): the push runs of the commit below vouch for the same code. Prints the commit, then, while the
# current commit's own change touches only documentation, its first parent, up to and including the first commit
# that touches anything else, or a root commit.
set -euo pipefail

c=$1
while :; do
    echo "$c"
    git rev-parse -q --verify "$c^" >/dev/null || break
    git diff --quiet "$c^" "$c" -- . ':!*.md' ':!wiki/**' || break
    c=$(git rev-parse "$c^")
done
