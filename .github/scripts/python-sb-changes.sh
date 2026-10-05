#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Job build of release.yml. Usage: python-sb-changes.sh <tag>
# python-sb/ is a separate package with its own version. It is published when one of its files changed since the
# previous release tag, and then its version must be higher than at that tag: a change left at the same version would
# be skipped by the index without a word. python-sb uses final versions only (X.Y.Z): sort -V does not order
# PEP 440 pre-releases. Prints publish=true|false and version=… for $GITHUB_OUTPUT.
set -euo pipefail

tag=$1
version_at() {
    git show "$1:python-sb/pyproject.toml" | sed -n 's/^version = "\([^"]*\)".*/\1/p'
}

version=$(version_at "$tag")
previous=$(git describe --tags --abbrev=0 --match 'v[0-9]*' "$tag^" 2>/dev/null || true)
publish=true
if [[ -n $previous ]]; then
    if git diff --quiet "$previous" "$tag" -- python-sb/; then
        publish=false
    else
        old=$(version_at "$previous")
        if [[ $version == "$old" || $(printf '%s\n%s\n' "$old" "$version" | sort -V | tail -n 1) != "$version" ]]; then
            echo "python-sb/ changed since $previous but its version is $version (was $old): bump it" >&2
            exit 1
        fi
    fi
fi
echo "publish=$publish"
echo "version=$version"
