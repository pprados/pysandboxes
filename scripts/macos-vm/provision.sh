#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Runs inside the macOS VM, over SSH (make init-macos-vm): installs what the suites of cross-os.yml need there.
# Idempotent. Uses bash 3.2, the one macOS ships.
set -eu
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"
openssl_version="${OPENSSL_VERSION:-3.5.9}"

if ! xcode-select -p >/dev/null 2>&1 || ! command -v cc >/dev/null 2>&1; then
  echo "The command line tools are missing in the VM: run 'xcode-select --install' in its Terminal, then run this again." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version

# cryptography has no wheel for this Intel macOS on Python 3.11 and 3.12, and builds from source: it needs an OpenSSL
# that the system does not provide.
if [ ! -x "$HOME/openssl/bin/openssl" ]; then
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl -fsSL -o "$work/openssl.tar.gz" "https://github.com/openssl/openssl/releases/download/openssl-$openssl_version/openssl-$openssl_version.tar.gz"
  tar -xzf "$work/openssl.tar.gz" -C "$work"
  (cd "$work/openssl-$openssl_version" && ./Configure --prefix="$HOME/openssl" --openssldir="$HOME/openssl" no-tests >/dev/null && make -j"$(sysctl -n hw.ncpu)" >/dev/null && make install_sw >/dev/null)
fi
"$HOME/openssl/bin/openssl" version

# The release-script tests need GNU sed, jq and sha256sum, which macOS lacks and brew cannot install here without
# a sudo password: they go under $HOME/gnu/bin, which `make macos-tests` puts first in the PATH.
gnu="$HOME/gnu/bin"
mkdir -p "$gnu"
if ! "$gnu/sed" --version >/dev/null 2>&1; then
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl -fsSL -o "$work/sed.tar.xz" https://ftp.gnu.org/gnu/sed/sed-4.9.tar.xz
  echo "6e226b732e1cd739464ad6862bd1a1aba42d7982922da7a53519631d24975181  $work/sed.tar.xz" | shasum -a 256 -c - >/dev/null
  tar -xJf "$work/sed.tar.xz" -C "$work"
  (cd "$work/sed-4.9" && ./configure --prefix="$HOME/gnu" --disable-nls >/dev/null && make -j"$(sysctl -n hw.ncpu)" >/dev/null && make install >/dev/null)
fi
if [ ! -x "$gnu/jq" ]; then
  curl -fsSL -o "$gnu/jq" https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-macos-amd64
  echo "4155822bbf5ea90f5c79cf254665975eb4274d426d0709770c21774de5407443  $gnu/jq" | shasum -a 256 -c - >/dev/null
  chmod 755 "$gnu/jq"
fi
# LanceDB has no wheel for this Intel macOS: the crewai sample builds it from source, and its build needs protoc.
if [ ! -x "$gnu/protoc" ]; then
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl -fsSL -o "$work/protoc.zip" https://github.com/protocolbuffers/protobuf/releases/download/v36.2/protoc-36.2-osx-x86_64.zip
  echo "228cc7add4616cc14ca5e80dee83209d44449a7aee95a914ae748fa374efb078  $work/protoc.zip" | shasum -a 256 -c - >/dev/null
  unzip -q "$work/protoc.zip" -d "$HOME/gnu"
  chmod 755 "$gnu/protoc"
fi
printf '#!/bin/sh\nexec shasum -a 256 "$@"\n' > "$gnu/sha256sum"
chmod 755 "$gnu/sha256sum"
"$gnu/sed" --version | head -n 1
"$gnu/jq" --version
"$gnu/protoc" --version

mkdir -p "$HOME/pysandboxes"
echo "VM ready: uv, a compiler and OpenSSL are in place."
