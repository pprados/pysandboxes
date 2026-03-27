#!/bin/bash

# Exit on error and print commands
set -e
# set -x

# --- 1. NETWORK SETUP ---
# Initialize loopback interface
ip link set lo up
# Apply firewall rules if present
if [ -e "iptables.rules" ]; then
    iptables-restore < iptables.rules
fi

# --- 2. PREPARE NEW ISOLATED ROOT ---
# Create a temporary directory to act as the new root filesystem
NEW_ROOT=$(mktemp -d)
mount -t tmpfs none "$NEW_ROOT"

# Create essential system directories
mkdir -p "$NEW_ROOT"/{dev,proc,tmp,bin,lib,lib64,usr,etc,home,root}

# Helper function for secure read-only bind mounts
mount_readonly() {
    local src=$1
    local dst="$NEW_ROOT${2:-$1}"
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
mount_readwrite() {
    local src=$1
    local dst="$NEW_ROOT${2:-$1}"
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
# Move to the new root directory and drop privileges
cd "$NEW_ROOT"
# Use chroot to enter the isolated environment and setpriv to drop all capabilities
echo "Sandbox locked. Entering environment..."
exec chroot . setpriv --inh-caps=-all --bounding-set=-all -- "$@"