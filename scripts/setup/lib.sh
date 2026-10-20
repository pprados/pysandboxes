# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Helpers shared by the setup scripts. Source it, do not run it.

# linux, wsl, macos, windows (Git Bash, MSYS, Cygwin) or unknown.
detect_os() {
  case "$(uname -s)" in
    Linux) if grep -qi microsoft /proc/version 2>/dev/null; then echo wsl; else echo linux; fi ;;
    Darwin) echo macos ;;
    MINGW* | MSYS* | CYGWIN*) echo windows ;;
    *) echo unknown ;;
  esac
}

# apt-get, dnf, or nothing.
pkg_manager() {
  local manager
  for manager in apt-get dnf; do
    if command -v "$manager" >/dev/null 2>&1; then echo "$manager"; return 0; fi
  done
  return 1
}

# confirm "question": YES=1 answers yes, and a run without a terminal answers no.
confirm() {
  if [ "${YES:-}" = 1 ]; then return 0; fi
  if [ ! -t 0 ]; then echo "$1 -- no terminal: run with YES=1 to accept." >&2; return 1; fi
  local answer
  read -r -p "$1 [y/N] " answer
  [[ $answer =~ ^[yY] ]]
}

# confirm_security "question" VARIABLE: a change that weakens the host is never accepted by YES=1,
# only by an explicit answer or by VARIABLE=1.
confirm_security() {
  if [ "${!2:-}" = 1 ]; then return 0; fi
  if [ ! -t 0 ]; then echo "$1 -- no terminal: run with $2=1 to accept." >&2; return 1; fi
  local answer
  read -r -p "$1 [y/N] " answer
  [[ $answer =~ ^[yY] ]]
}

# The tools of a Linux workstation, as command:apt package:dnf package. `required` ones stop the doctor.
LINUX_REQUIRED=(
  "git:git:git"
  "make:make:make"
  "curl:curl:curl"
  "gcc:build-essential:gcc"
)
# One OS provider, or one family of tests, each, which skips itself without its tool.
LINUX_PROVIDER_TOOLS=(
  "bwrap:bubblewrap:bubblewrap"
  "firejail:firejail:firejail"
  "slirp4netns:slirp4netns:slirp4netns"
  "iptables:iptables:iptables"
  "ip:iproute2:iproute"
  "qemu-system-x86_64:qemu-system-x86:qemu-system-x86-core"
  "qemu-img:qemu-utils:qemu-img"
  "genisoimage:genisoimage:genisoimage"
)

# package_of <entry> <apt-get|dnf>
package_of() {
  local IFS=:
  # shellcheck disable=SC2206
  local parts=($1)
  if [ "$2" = dnf ]; then echo "${parts[2]}"; else echo "${parts[1]}"; fi
}

command_of() { echo "${1%%:*}"; }

add_uv_to_path() {
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
}
