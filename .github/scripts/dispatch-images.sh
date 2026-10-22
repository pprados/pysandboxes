#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Behind the images job of release.yml. Usage: dispatch-images.sh <tag>
# Dispatches images.yml on the tag, waits for its run and fails when that run fails. images.yml is dispatched, not
# called: a called workflow does not receive the secrets of its own environment, so the Docker Hub login got none.
set -euo pipefail

tag=${1:?Usage: dispatch-images.sh <tag>}
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh workflow run images.yml --ref "$tag"

run=
for _ in $(seq 30); do
    run=$(gh run list --workflow images.yml --event workflow_dispatch --branch "$tag" --json databaseId,createdAt \
        --jq "[.[] | select(.createdAt >= \"$since\")] | sort_by(.createdAt) | first | .databaseId // empty")
    [[ -n $run ]] && break
    sleep 10
done
[[ -n $run ]] || {
    echo "images.yml was dispatched on $tag but its run did not appear within 5 minutes" >&2
    exit 1
}
echo "images.yml run $run: https://github.com/$GITHUB_REPOSITORY/actions/runs/$run"
gh run watch "$run" --interval 30 --exit-status
