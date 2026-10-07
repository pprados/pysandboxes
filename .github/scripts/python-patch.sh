#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Run by images.yml and images-refresh.yml. Usage: python-patch.sh <python minor>
# Prints the Python patch that python:<minor>-slim holds today, read from the PYTHON_VERSION its image sets, so the
# images are built FROM python:<patch>-slim and tagged with the patch they really hold.
set -euo pipefail

minor=$1
engine=${CONTAINER_CMD:-docker}

if [[ ! $minor =~ ^[0-9]+\.[0-9]+$ ]]; then
    echo "$minor: not a X.Y Python version" >&2
    exit 1
fi
"$engine" pull --quiet "python:$minor-slim" >/dev/null
patch=$("$engine" image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "python:$minor-slim" |
    sed -n 's/^PYTHON_VERSION=//p')
if [[ ! $patch =~ ^${minor//./\\.}\.[0-9]+$ ]]; then
    echo "python:$minor-slim holds Python '$patch', not a $minor.N release" >&2
    exit 1
fi
echo "$patch"
