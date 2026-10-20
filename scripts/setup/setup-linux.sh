#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Install what a Linux or WSL2 workstation lacks: system packages, uv, and, on request, the AppArmor setting that
# lets bwrap and unshare create user namespaces. Asks before it changes anything; YES=1 accepts the packages and uv.
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
add_uv_to_path

manager="$(pkg_manager)" || {
  echo "Neither apt-get nor dnf found: install the tools listed by 'make doctor' with your package manager." >&2
  exit 1
}

packages=()
for entry in "${LINUX_REQUIRED[@]}" "${LINUX_PROVIDER_TOOLS[@]}"; do
  command -v "$(command_of "$entry")" >/dev/null 2>&1 || packages+=("$(package_of "$entry" "$manager")")
done

if [ "${#packages[@]}" -gt 0 ]; then
  echo "Missing packages: ${packages[*]}"
  if confirm "Install them with sudo $manager?"; then
    if [ "$manager" = apt-get ]; then sudo apt-get update; fi
    if [ "$manager" = apt-get ]; then
      sudo apt-get install -y --no-install-recommends "${packages[@]}"
    else
      sudo dnf install -y --setopt=install_weak_deps=False "${packages[@]}"
    fi
  else
    echo "Skipped: the providers that need them will skip their tests."
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  if confirm "Install uv from https://astral.sh/uv/install.sh?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  else
    echo "uv is required: https://docs.astral.sh/uv/" >&2
    exit 1
  fi
fi

key=/proc/sys/kernel/apparmor_restrict_unprivileged_userns
if [ -r "$key" ] && [ "$(cat "$key")" = 1 ]; then
  echo
  echo "AppArmor forbids unprivileged user namespaces here, and bwrap and unshare need them."
  echo "Lifting it lets any local user create a user namespace, which widens the kernel attack surface (wiki/unshare.md)."
  if confirm_security "Set kernel.apparmor_restrict_unprivileged_userns=0, now and at every boot?" RELAX_APPARMOR; then
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    echo "kernel.apparmor_restrict_unprivileged_userns=0" | sudo tee /etc/sysctl.d/60-pysandboxes.conf >/dev/null
  else
    echo "Left as is: the bwrap and unshare rows will skip or fail."
  fi
fi

if [ -e /dev/kvm ] && [ ! -w /dev/kvm ]; then
  echo
  echo "/dev/kvm exists but you cannot write it: sudo usermod -aG kvm \$USER, then log in again (qemu, windows-vm, macos-vm)."
fi
