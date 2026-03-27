#!/bin/bash

# Exit on error, undefined variables, and pipe failures
set -euo pipefail
#set -x

# --- 1. NETWORK SETUP ---
# Initialize loopback interface
ip link set lo up
# Apply firewall rules if present
if [ -f "iptables.rules" ]; then
    iptables-restore < "iptables.rules"
fi

# --- 2. PREPARE NEW ISOLATED ROOT ---
# Create a temporary directory to act as the new root filesystem
NEW_ROOT=$(mktemp -d)
mount -t tmpfs none "$NEW_ROOT"

# Create essential system directories
mkdir -p "$NEW_ROOT"/{dev,proc,tmp,bin,lib,lib64,usr,etc,home,root}

# Helper function for secure read-only bind mounts
# Usage: mount_readonly <source_path> [destination_path]
# If destination_path is not provided, it defaults to source_path
mount_readonly() {
    local src=$1
    local dst_path=${2:-$1}
    local dst="$NEW_ROOT$dst_path"
    if [ -e "$src" ]; then
        if [ -d "$src" ]; then
            mkdir -p "$dst"
        else
            mkdir -p "$(dirname "$dst")"
            touch "$dst"
        fi
        mount --bind "$src" "$dst"
        mount -o remount,ro,bind,nosuid,nodev "$dst"
    fi
}

# Helper function for secure read-write bind mounts
# Usage: mount_readwrite <source_path> [destination_path]
# If destination_path is not provided, it defaults to source_path
mount_readwrite() {
    local src=$1
    local dst_path=${2:-$1}
    local dst="$NEW_ROOT$dst_path"
    if [ -e "$src" ]; then
        if [ -d "$src" ]; then
            mkdir -p "$dst"
        else
            mkdir -p "$(dirname "$dst")"
            touch "$dst"
        fi
        mount --bind "$src" "$dst"
    fi
}

# Helper function to hide paths
hide_path() {
    local dst="$NEW_ROOT$1"
    if [ -e "$1" ]; then
        if [ -d "$1" ]; then
            mkdir -p "$dst"
            mount -t tmpfs -o size=0 none "$dst"
        else
            mkdir -p "$(dirname "$dst")"
            touch "$dst"
            mount --bind /dev/null "$dst"
        fi
    fi
}

# --- 3. MOUNT WORKSPACE AND TOOLS ---
# These will be populated by the daemon
${MOUNTS}

# Mount pseudo-filesystems
# For /dev, we use a tmpfs and bind selective nodes to avoid "wrong fs type" errors in user namespaces
mount -t tmpfs -o mode=755,nosuid none "$NEW_ROOT/dev"
for dev in null zero full random urandom tty; do
    if [ -e "/dev/$dev" ]; then
        touch "$NEW_ROOT/dev/$dev"
        mount --bind "/dev/$dev" "$NEW_ROOT/dev/$dev"
    fi
done
# Mount /dev/shm for POSIX semaphores (needed by Python multiprocessing)
mkdir -p "$NEW_ROOT/dev/shm"
mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs "$NEW_ROOT/dev/shm"

mount -t proc proc "$NEW_ROOT/proc"

# --- 4. ENTER SANDBOX ---
# Save original working directory before chroot
ORIGINAL_CWD=$(pwd)
# Move to the new root directory and drop privileges
cd "$NEW_ROOT"
# Use chroot to enter the isolated environment, then cd to original directory
# and use setpriv to drop all capabilities
# Verify setpriv is available
if ! command -v setpriv >/dev/null 2>&1; then
    echo "Error: setpriv command not found" >&2
    exit 1
fi
exec chroot . sh -c "cd \"$ORIGINAL_CWD\" && exec setpriv --inh-caps=-all --bounding-set=-all -- \"\$@\"" sh "$@"