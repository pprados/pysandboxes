#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Job verify-published of release.yml. Usage: verify-published.sh <version> <wheel>
# Downloads pysandboxes==<version> from the index and compares its sha256 with the wheel the release built, so the
# images embed exactly what was published. test.pypi.org sits behind a CDN: a file not visible yet is retried,
# a different file fails at once.
set -euo pipefail

version=$1
wheel=$2
index=${INDEX_URL:-https://test.pypi.org/simple/}
attempts=${ATTEMPTS:-30}
interval=${INTERVAL:-20}

expected=$(sha256sum "$wheel" | cut -d' ' -f1)
dest=$(mktemp -d)
for ((i = 1; i <= attempts; i++)); do
    if pip download "pysandboxes==$version" --no-deps --no-cache-dir --only-binary :all: --index-url "$index" \
            --dest "$dest" >/dev/null 2>&1; then
        published=$(sha256sum "$dest"/*.whl | cut -d' ' -f1)
        if [[ $published != "$expected" ]]; then
            echo "::error::the published wheel ($published) differs from the built one ($expected)"
            exit 1
        fi
        echo "The published wheel is the built one: sha256 $expected"
        exit 0
    fi
    if ((i < attempts)); then sleep "$interval"; fi
done
echo "::error::published but not visible yet, after $attempts attempts: re-run the failed jobs"
exit 1
