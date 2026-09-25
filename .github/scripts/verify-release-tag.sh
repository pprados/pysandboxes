#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# First job of release.yml. Usage: verify-release-tag.sh <refs/tags/vX.Y.ZbN>
# The trusted keys come from ALLOWED_SIGNERS (the repository variable RELEASE_ALLOWED_SIGNERS),
# never from a file of the tagged commit, which whoever writes to the repository controls.
# Prints version=… and sha=… for $GITHUB_OUTPUT.
set -euo pipefail

ref=$1
if [[ $ref != refs/tags/* ]]; then
    echo "not a tag: $ref" >&2
    exit 1
fi
tag=${ref#refs/tags/}

if [[ ! $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+(a|b|rc)[0-9]+$ ]]; then
    echo "$tag: final release not enabled yet, only vX.Y.Z(a|b|rc)N tags are published" >&2
    exit 1
fi

if [[ -z ${ALLOWED_SIGNERS:-} ]]; then
    echo "the repository variable RELEASE_ALLOWED_SIGNERS is empty" >&2
    exit 1
fi
signers=$(mktemp)
trap 'rm -f "$signers"' EXIT
printf '%s\n' "$ALLOWED_SIGNERS" >"$signers"
git -c gpg.ssh.allowedSignersFile="$signers" verify-tag "$tag"

sha=$(git rev-parse "$tag^{commit}")
if [[ $sha != "${GITHUB_SHA:-$sha}" ]]; then
    echo "$tag ($sha) is not the commit being built (${GITHUB_SHA})" >&2
    exit 1
fi
if ! git merge-base --is-ancestor "$sha" origin/develop; then
    echo "$tag ($sha) is not on develop" >&2
    exit 1
fi

echo "version=${tag#v}"
echo "sha=$sha"
