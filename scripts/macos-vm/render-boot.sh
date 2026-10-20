#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# render-boot.sh <install|ssh> <OpenCore-Boot.sh>: print the launcher of the macOS VM, derived from the OpenCore-Boot.sh
# of OSX-KVM, so that a new OSX-KVM revision only has to keep the lines it matches.
#   install  boots the installer: the Base System image stays attached, the display is on VNC.
#   ssh      boots the installed system: no installer, SSH forwarded on loopback, and autoboot.py picks the disk.
# MACOS_VM_RAM (MiB), MACOS_VM_CORES and MACOS_VM_SSH_PORT size the VM.
set -eu
variant="$1"
upstream="$2"
ram="${MACOS_VM_RAM:-8192}"
cores="${MACOS_VM_CORES:-4}"
port="${MACOS_VM_SSH_PORT:-2223}"

filters=(
  -e "s|^ALLOCATED_RAM=.*|ALLOCATED_RAM=\"$ram\" # MiB|"
  -e "s|^CPU_CORES=.*|CPU_CORES=\"$cores\"|"
  -e "s|^CPU_THREADS=.*|CPU_THREADS=\"$((cores * 2))\"|"
  -e 's|^REPO_PATH=.*|REPO_PATH="$(cd "$(dirname "$0")" \&\& pwd)"|'
  -e "s|hostfwd=tcp::2222-:22|hostfwd=tcp:127.0.0.1:$port-:22|"
  -e 's|^  -monitor stdio|  -monitor unix:$REPO_PATH/monitor.sock,server,nowait -qmp unix:$REPO_PATH/qmp.sock,server,nowait -display none -vnc 127.0.0.1:1|'
)
if [ "$variant" = ssh ]; then
  filters+=(
    -e '/InstallMedia/d'
    -e 's|^qemu-system-x86_64 "${args\[@\]}"|nohup python3 -I "$REPO_PATH/autoboot.py" >> "$REPO_PATH/autoboot.log" 2>\&1 < /dev/null \&\n&|'
  )
fi
sed "${filters[@]}" "$upstream"
