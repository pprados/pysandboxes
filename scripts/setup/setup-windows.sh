#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Install what native Windows lacks (Git Bash, MSYS or Cygwin) to run the Python layer of the suites.
# The kernel-backed providers need WSL2: run `make init` inside it instead. Asks before it installs; YES=1 accepts.
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"

echo "Recommended: WSL2, where every provider is available (wsl --install -d Ubuntu-24.04, from an administrator"
echo "PowerShell), then make init inside the Linux shell. What follows prepares native Windows, which runs the"
echo "subprocess provider only."
echo

if ! command -v winget >/dev/null 2>&1; then
  echo "winget is missing: install uv (https://docs.astral.sh/uv/), git and GNU make by hand." >&2
  exit 1
fi

ids=()
command -v uv >/dev/null 2>&1 || ids+=(astral-sh.uv)
command -v git >/dev/null 2>&1 || ids+=(Git.Git)
command -v make >/dev/null 2>&1 || ids+=(ezwinports.make)

if [ "${#ids[@]}" -gt 0 ]; then
  echo "Missing: ${ids[*]}"
  if confirm "Install them with winget?"; then
    for id in "${ids[@]}"; do winget install --id "$id" -e --accept-source-agreements --accept-package-agreements; done
    echo "Open a new shell so that the new PATH applies."
  fi
fi
