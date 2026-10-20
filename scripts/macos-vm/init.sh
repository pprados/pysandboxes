#!/usr/bin/env bash
# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# make init-macos-vm: build the local macOS VM with OSX-KVM, then provision it. Idempotent: run it again after each
# manual step. Intel x86_64 Linux host with KVM only; the guest is an Intel macOS, which says nothing about Apple Silicon.
#
#   1. downloads macOS and prepares the disk (after an explicit validation),
#   2. writes the launchers, the SSH key and the SSH config next to OSX-KVM,
#   3. when the VM answers on SSH, installs what the suites need in it (provision.sh).
# The macOS installation itself is interactive (VNC) and cannot be scripted: the steps are printed.
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dir="${MACOS_VM_DIR:-$HOME/.pysandboxes/macos-vm}"
osx_kvm="${OSX_KVM_DIR:-$dir/OSX-KVM}"
osx_kvm_commit="4c378a4b5e0b219783683012bec680325eb40719"
shortname="${MACOS_SHORTNAME:-sonoma}"
disk_size="${MACOS_DISK_SIZE:-64G}"
port="${MACOS_VM_SSH_PORT:-2223}"
user="${MACOS_VM_USER:-mac}"
ssh_config="$osx_kvm/ssh_config"

fail() { echo "$*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || fail "The macOS VM runs on a Linux host with KVM. On a Mac, work on the Mac itself: make macos-tests is not needed."
[ "$(uname -m)" = x86_64 ] || fail "OSX-KVM needs an x86_64 host: the guest is an Intel macOS."
for tool in git python3 qemu-system-x86_64 qemu-img ssh ssh-keygen; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is missing: run make init, then make doctor."
done
{ [ -r /dev/kvm ] && [ -w /dev/kvm ]; } || fail "/dev/kvm is absent or not writable: sudo usermod -aG kvm \$USER, then log in again."

vm_reachable() { ssh -F "$ssh_config" -o BatchMode=yes -o ConnectTimeout=5 macos true >/dev/null 2>&1; }

if [ ! -f "$osx_kvm/BaseSystem.img" ] || [ ! -f "$osx_kvm/mac_hdd_ng.img" ]; then
  cat <<TEXT
This builds a macOS $shortname virtual machine with OSX-KVM (https://github.com/kholia/OSX-KVM).

  * Apple's licence allows macOS in a virtual machine on Apple-branded hardware only. Build it only where your
    licence allows. It exists to run the macOS rows of cross-os.yml from a Linux workstation; a contributor who has
    a Mac does not need it.
  * It is an Intel guest. It proves the Intel macOS behaviour, not Apple Silicon's.
  * It downloads about 750 MB from Apple's servers, takes $disk_size of disk and about 1 hour, most of it the
    interactive macOS installation.
  * Everything goes under $dir.
TEXT
  if [ "${MACOS_VM_ACCEPT:-}" != yes ]; then
    [ -t 0 ] || fail "No terminal: run with MACOS_VM_ACCEPT=yes to accept the points above."
    read -r -p "Type 'yes' to continue: " answer
    [ "$answer" = yes ] || fail "Not accepted."
  fi
fi

mkdir -p "$dir"
if [ ! -d "$osx_kvm/.git" ]; then git clone https://github.com/kholia/OSX-KVM.git "$osx_kvm"; fi
git -C "$osx_kvm" checkout --quiet "$osx_kvm_commit" 2>/dev/null || echo "OSX-KVM is not at the tested revision $osx_kvm_commit; the launchers may not match."

make -C "$osx_kvm" SHORTNAME="$shortname" DISK_SIZE="$disk_size" BaseSystem.img mac_hdd_ng.img

install -m 755 "$here/autoboot.py" "$osx_kvm/autoboot.py"
"$here/render-boot.sh" install "$osx_kvm/OpenCore-Boot.sh" > "$osx_kvm/boot-install.sh"
"$here/render-boot.sh" ssh "$osx_kvm/OpenCore-Boot.sh" > "$osx_kvm/boot-ssh.sh"
chmod 755 "$osx_kvm/boot-install.sh" "$osx_kvm/boot-ssh.sh"

if [ ! -f "$osx_kvm/id_macos" ]; then ssh-keygen -q -t ed25519 -N '' -f "$osx_kvm/id_macos"; fi
cat > "$ssh_config" <<CONFIG
Host macos
  HostName 127.0.0.1
  Port $port
  User $user
  IdentityFile $osx_kvm/id_macos
  IdentitiesOnly yes
  UserKnownHostsFile $osx_kvm/known_hosts
  StrictHostKeyChecking accept-new
CONFIG

if vm_reachable; then
  echo "The VM answers on SSH: provisioning it."
  ssh -F "$ssh_config" macos 'bash -s' < "$here/provision.sh"
  echo
  echo "Done. Export OSX_KVM_DIR=$osx_kvm if it is not the default, then: make macos-tests"
  exit 0
fi

cat <<TEXT

The VM does not answer on SSH yet. If macOS is not installed:

  1. Start the installer:      $osx_kvm/boot-install.sh
     and open a VNC viewer on 127.0.0.1:5901.
  2. In the OpenCore picker choose "macOS Base System" (or "Install macOS"). In Disk Utility erase the large disk
     as APFS named "Macintosh HD", then reinstall macOS. The VM restarts several times: choose the installer
     entry, then "Macintosh HD", until the setup assistant runs.
  3. In the assistant create the user '$user'. Skip every optional step (Apple ID, analytics, Siri).
  4. Open Terminal in the VM and paste:
       sudo systemsetup -setremotelogin on
       mkdir -p ~/.ssh && chmod 700 ~/.ssh
       echo '$(cat "$osx_kvm/id_macos.pub")' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
       xcode-select --install
     and accept the command line tools installation.
  5. Shut the VM down, then boot the installed system:   make macos-vm
  6. Run make init-macos-vm again: it provisions the VM.
TEXT
