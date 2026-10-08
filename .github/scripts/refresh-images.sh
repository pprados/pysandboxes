#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Run daily by images-refresh.yml. Usage: refresh-images.sh <python minor>...
# Prints, for $GITHUB_OUTPUT, the latest final release tag (tag=vX.Y.Z) and the JSON list of the Python minors whose
# newest patch has no image of that release yet (minors=[...]). No final release yet: minors=[]. The image probed is
# python-sb-qemu, the last one images.yml pushes, so that a push that stopped half-way is done again.
set -euo pipefail

engine=${CONTAINER_CMD:-docker}
here=$(dirname "$0")

tag=$(git tag --list 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)
if [[ -z $tag ]]; then
    echo "No final release: nothing to refresh" >&2
    echo "minors=[]"
    exit 0
fi

missing=()
for minor in "$@"; do
    patch=$("$here/python-patch.sh" "$minor")
    image="docker.io/pprados/python-sb-qemu:$patch-sb${tag#v}"
    if "$engine" manifest inspect "$image" >/dev/null 2>&1; then
        echo "$image: present" >&2
    else
        echo "$image: missing" >&2
        missing+=("\"$minor\"")
    fi
done
echo "tag=$tag"
echo "minors=[$(IFS=,; echo "${missing[*]}")]"
