#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# make init: detect the system, install what it lacks, sync the environments, then report what is still missing.
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
add_uv_to_path

os="$(detect_os)"
echo "System detected: $os"
case "$os" in
  linux | wsl) "$here/setup-linux.sh" ;;
  macos) "$here/setup-macos.sh" ;;
  windows) "$here/setup-windows.sh" ;;
  *) echo "Unsupported system: $(uname -s). Use Linux, WSL2, macOS or Git Bash." >&2; exit 1 ;;
esac

add_uv_to_path
# A distribution Python (Ubuntu 24.04's 3.12.3) lacks modules the guards and the tests expect: uv gets its own.
uv sync --python-preference only-managed ${UV_GROUP:---group dev --group test --group lint}

if command -v gh >/dev/null 2>&1 && ! gh extension list 2>/dev/null | grep -q gh-act; then
  gh extension install https://github.com/nektos/gh-act || echo "gh act not installed: make gh-tests will not run."
fi
if command -v git-lfs >/dev/null 2>&1; then git lfs install 2>/dev/null || true; fi

echo
exec "$here/doctor.sh"
