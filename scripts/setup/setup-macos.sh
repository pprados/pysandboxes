#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Install what a Mac lacks to run the Python layer of the suites: the command line tools, Homebrew packages, uv.
# Asks before it installs; YES=1 accepts.
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
add_uv_to_path

if ! xcode-select -p >/dev/null 2>&1; then
  echo "The Xcode command line tools are missing (compiler, git, make)."
  if confirm "Run xcode-select --install? (a window asks for confirmation; run this again when it ends)"; then
    xcode-select --install || true
  fi
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is missing: https://brew.sh. Install it, then run this again." >&2
  echo "Without it, install uv with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

formulae=()
command -v uv >/dev/null 2>&1 || formulae+=(uv)
command -v git-lfs >/dev/null 2>&1 || formulae+=(git-lfs)
command -v gh >/dev/null 2>&1 || formulae+=(gh)
# The release-script tests (tag-release, changelog-draft, ...) need GNU sed, jq and sha256sum, which macOS lacks.
sed --version 2>/dev/null | grep -q GNU || brew list gnu-sed >/dev/null 2>&1 || formulae+=(gnu-sed)
command -v jq >/dev/null 2>&1 || formulae+=(jq)
command -v sha256sum >/dev/null 2>&1 || brew list coreutils >/dev/null 2>&1 || formulae+=(coreutils)
if [ "$(uname -m)" = x86_64 ] && ! brew list openssl@3 >/dev/null 2>&1; then formulae+=(openssl@3); fi

if [ "${#formulae[@]}" -gt 0 ]; then
  echo "Missing formulae: ${formulae[*]}"
  if confirm "Install them with brew?"; then
    brew install "${formulae[@]}"
  fi
fi
echo
echo "To run the release-script tests, put the GNU tools first in the PATH (the suites leave those tests out without them):"
echo "  export PATH=\"\$(brew --prefix gnu-sed)/libexec/gnubin:\$(brew --prefix coreutils)/libexec/gnubin:\$PATH\""
if [ "$(uname -m)" = x86_64 ]; then
  echo
  echo "Intel Mac: if uv sync builds cryptography from source and cannot find OpenSSL, run first:"
  echo "  export OPENSSL_DIR=\$(brew --prefix openssl@3)"
fi
echo
echo "macOS runs the subprocess provider only. For bwrap, unshare, landlock, firejail and qemu, work in a Linux VM."
