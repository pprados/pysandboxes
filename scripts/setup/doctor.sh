#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Report the tools and the kernel settings a contributor needs, and what each missing one costs.
# Exit status 1 when a required tool is missing. Changes nothing.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
add_uv_to_path

os="$(detect_os)"
manager="$(pkg_manager || true)"
required_missing=0
optional_missing=0

ok() { printf '%-10s %-24s %s\n' "[ok]" "$1" "$2"; }
missing_required() { printf '%-10s %-24s %s\n' "[MISSING]" "$1" "$2"; required_missing=$((required_missing + 1)); }
missing_optional() { printf '%-10s %-24s %s\n' "[missing]" "$1" "$2"; optional_missing=$((optional_missing + 1)); }

install_hint() { # install_hint <apt package> <dnf package>
  case "$manager" in
    apt-get) echo "sudo apt-get install $1" ;;
    dnf) echo "sudo dnf install $2" ;;
    *) echo "install $1" ;;
  esac
}

check_entry() { # check_entry <required|optional> <entry> <consequence>
  local command package
  command="$(command_of "$2")"
  if command -v "$command" >/dev/null 2>&1; then
    ok "$command" "$(command -v "$command")"
    return
  fi
  package="$(package_of "$2" "${manager:-apt-get}")"
  if [ "$1" = required ]; then
    missing_required "$command" "$3. $(install_hint "$(package_of "$2" apt-get)" "$(package_of "$2" dnf)")"
  else
    missing_optional "$command" "$3. $(install_hint "$(package_of "$2" apt-get)" "$(package_of "$2" dnf)") [$package]"
  fi
}

check_command() { # check_command <required|optional> <command> <consequence and remedy>
  if command -v "$2" >/dev/null 2>&1; then
    ok "$2" "$(command -v "$2")"
  elif [ "$1" = required ]; then
    missing_required "$2" "$3"
  else
    missing_optional "$2" "$3"
  fi
}

check_kernel_setting() { # check_kernel_setting <file> <good value> <consequence and remedy>
  local value
  [ -r "$1" ] || return 0
  value="$(cat "$1")"
  if [ "$value" = "$2" ]; then ok "$(basename "$1")" "$value"; else missing_optional "$(basename "$1")" "is $value, must be $2: $3"; fi
}

echo "System: $os ($(uname -sm))"
echo

echo "== Needed by every suite"
check_command required uv "Install it: curl -LsSf https://astral.sh/uv/install.sh | sh (scripts/setup/init.sh does it)"
case "$os" in
  linux | wsl)
    for entry in "${LINUX_REQUIRED[@]}"; do check_entry required "$entry" "needed to build and run the suites"; done
    ;;
  macos)
    check_command required git "Install the Xcode command line tools: xcode-select --install"
    check_command required make "Install the Xcode command line tools: xcode-select --install"
    check_command required cc "Install the Xcode command line tools: xcode-select --install"
    ;;
  windows)
    check_command required git "winget install --id Git.Git"
    check_command required make "winget install --id ezwinports.make, or work in WSL2 (recommended)"
    ;;
esac

echo
echo "== Optional"
check_command optional gh "needed by make gh-tests (gh act) and by the CI helpers; https://cli.github.com"
check_command optional git-lfs "needed to fetch the files kept in git lfs"

case "$os" in
  linux | wsl)
    echo
    echo "== OS providers (a provider without its tool skips its tests, which then prove nothing about it)"
    for entry in "${LINUX_PROVIDER_TOOLS[@]}"; do check_entry optional "$entry" "its provider rows skip"; done

    echo
    echo "== Kernel"
    check_kernel_setting /proc/sys/kernel/apparmor_restrict_unprivileged_userns 0 \
      "bwrap and unshare cannot create a user namespace: sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 (see wiki/unshare.md for the risk)"
    check_kernel_setting /proc/sys/kernel/unprivileged_userns_clone 1 \
      "sudo sysctl -w kernel.unprivileged_userns_clone=1"
    if [ -r /proc/sys/user/max_user_namespaces ] && [ "$(cat /proc/sys/user/max_user_namespaces)" = 0 ]; then
      missing_optional "max_user_namespaces" "is 0: user namespaces are off, so bwrap and unshare cannot run"
    fi
    if [ -r /sys/kernel/security/lsm ] && grep -q landlock /sys/kernel/security/lsm; then
      ok "landlock" "enabled (/sys/kernel/security/lsm)"
    else
      missing_optional "landlock" "not listed in /sys/kernel/security/lsm: the landlock provider skips (needs Linux 5.13+; WSL2 kernels are reported to have it)"
    fi
    if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
      ok "/dev/kvm" "usable"
    else
      missing_optional "/dev/kvm" "absent or not writable: qemu falls back to the slow TCG row, and the Windows and macOS VMs cannot run (sudo usermod -aG kvm \$USER, then log in again)"
    fi

    echo
    echo "== Containers and VMs (make container-tests, windows-vm, macos-vm)"
    if command -v podman >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then
      ok "podman or docker" "$(command -v podman || command -v docker)"
    else
      missing_optional "podman or docker" "make container-tests and make windows-vm need one of them"
    fi
    check_command optional minikube "the Kubernetes rows of make container-tests skip"
    check_command optional kubectl "the Kubernetes rows of make container-tests skip"
    ;;
  macos)
    echo
    echo "== Scope"
    echo "macOS runs the Python layer over the subprocess provider only: the kernel-backed providers are Linux technology."
    echo "To run them, work in a Linux VM (Lima, Colima, Multipass, UTM): see CONTRIBUTING.md."
    if [ "$(uname -m)" = x86_64 ]; then
      echo "Intel Mac: cryptography may build from source on Python 3.11 and 3.12 and then needs OpenSSL:"
      echo "  brew install openssl@3 && export OPENSSL_DIR=\$(brew --prefix openssl@3)"
    fi
    ;;
  windows)
    echo
    echo "== Scope"
    echo "Native Windows runs the Python layer over the subprocess provider only."
    echo "For the kernel-backed providers use WSL2 (wsl --install -d Ubuntu-24.04) and run make init inside it."
    ;;
esac

echo
if [ "$required_missing" -gt 0 ]; then
  echo "$required_missing required tool(s) missing. scripts/setup/init.sh installs them on this system (make init does the same once make is installed)."
  exit 1
fi
echo "Nothing required is missing; $optional_missing optional item(s) missing."
