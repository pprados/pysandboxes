#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Run by the images job of release.yml. Usage: image-tags.sh <version> <python version> <default python version>
# Prints the Docker Hub tags of one image, one per line, in the manner of the official python images: the image is
# Python with pysandboxes. <python>-<version> never moves, nor does <version>, given to the default Python only. The
# moving tags, <python>, then 3 and latest (default Python only), follow final releases only, so that a pre-release
# never reaches a plain `docker pull`.
set -euo pipefail

version=$1
python=$2
default=$3

if [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    final=true
elif [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(a|b|rc)[0-9]+$ ]]; then
    final=false
else
    echo "$version: not a X.Y.Z or X.Y.Z(a|b|rc)N version" >&2
    exit 1
fi

if [[ $python == "$default" ]]; then
    echo "$version"
fi
echo "$python-$version"
if $final; then
    echo "$python"
    if [[ $python == "$default" ]]; then
        echo "3"
        echo "latest"
    fi
fi
