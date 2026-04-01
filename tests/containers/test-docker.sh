#!/usr/bin/env bash
# Run tests with docker (delegates to test-podman.sh, only DOCKER_CMD is changed).
set -euo pipefail

export DOCKER_CMD=docker
exec "$(dirname "$0")/test-podman.sh" "$@"
