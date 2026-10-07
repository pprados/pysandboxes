#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Run by images.yml. Usage: image-tags.sh <version> <python patch> <default python minor>
# Prints the Docker Hub tags of one image, one per line. The Python part stays bare, in the manner of the official
# python images; the pysandboxes version carries the sb prefix, so 3.13.2 is always Python, never pysandboxes.
# <patch>-sb<version> never moves. <minor>-sb<version>, then sb<version> (default Python only), move to the newest
# Python patch. The plain Python tags, <patch>, <minor>, then 3 and latest (default Python only), follow final
# releases only, so that a pre-release never reaches a plain `docker pull`.
set -euo pipefail

version=$1
patch=$2
default=$3

if [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    final=true
elif [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(a|b|rc)[0-9]+$ ]]; then
    final=false
else
    echo "$version: not a X.Y.Z or X.Y.Z(a|b|rc)N version" >&2
    exit 1
fi
if [[ ! $patch =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "$patch: not a X.Y.Z Python version" >&2
    exit 1
fi
minor=${patch%.*}

echo "$patch-sb$version"
echo "$minor-sb$version"
if [[ $minor == "$default" ]]; then
    echo "sb$version"
fi
if $final; then
    echo "$patch"
    echo "$minor"
    if [[ $minor == "$default" ]]; then
        echo "3"
        echo "latest"
    fi
fi
