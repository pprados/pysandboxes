#!/bin/bash
# This script is executed by unshare_launch.sh inside a user/network namespace.
set -euo pipefail

# These variables are placeholders replaced by the Python template engine.
export DNS_SERVER='${PYSANDBOXES_DNS}'
export PYSANDBOXES_HOSTS='${PYSANDBOXES_HOSTS}'
export PYSANDBOXES_MOUNTS='${PYSANDBOXES_MOUNTS}'
export PYSANDBOXES_NAMED_PIPE='${PYSANDBOXES_NAMED_PIPE}'
export CURRENT_DIR="$(pwd)"

# --- A. INITIALIZE NETWORK ---
# Signal readiness to the parent process.
echo $$ > "$PID_FILE"
# Wait for the parent to configure the network interface (slirp4netns).
read -n 1 -u 3
exec 3<&-

# Bring up the loopback interface.
ip link set lo up
ip addr add 127.0.0.1/8 dev lo || true

# --- B. PREPARE CONFIGURATION FILES (CONDITIONAL) ---
if [ -n "${DNS_SERVER:-}" ]; then
    echo "USE DNS"
    SANDBOX_RESOLV_CONF_IPTABLES=$(mktemp)
    # Support multiple DNS servers separated by spaces.
    read -r -a dns_array <<< "$DNS_SERVER"
    for dns in "${dns_array[@]}"; do
        echo "nameserver $dns" >> "$SANDBOX_RESOLV_CONF_IPTABLES"
    done

    SANDBOX_HOSTS_IPTABLES=$(mktemp)
    echo "127.0.0.1 localhost" > "$SANDBOX_HOSTS_IPTABLES"
    if [ -n "${PYSANDBOXES_HOSTS:-}" ]; then
        echo "${PYSANDBOXES_HOSTS}" | tr ";" "\n" >> "$SANDBOX_HOSTS_IPTABLES"
    fi

    # --- C. APPLY FIREWALL RULES ---
#    if [ -f "iptables.rules" ]; then
#        iptables-restore < "iptables.rules"
#    fi
fi

# --- D. PREPARE NEW ISOLATED ROOT (CHROOT) ---
NEW_ROOT=$(mktemp -d)
mount -t tmpfs none "$NEW_ROOT"
mkdir -p "$NEW_ROOT"/{dev,proc,tmp,etc,home,root}
chmod 1777 "$NEW_ROOT/tmp"

# Helper function to mount a path read-only.
mount_ro() {
    local src=$1
    local dst_path=${2:-$1}
    local dst="$NEW_ROOT$dst_path"
    if [ -e "$src" ]; then
        if [ -d "$src" ]; then mkdir -p "$dst"; else mkdir -p "$(dirname "$dst")"; touch "$dst"; fi
        mount --bind "$src" "$dst"
        mount -o remount,ro,bind,nosuid,nodev "$dst"
    fi
}

# Helper function to mount a path read-write.
mount_rw() {
    local src=$1
    local dst_path=${2:-$1}
    local dst="$NEW_ROOT$dst_path"
    if [ -e "$src" ]; then
        if [ -d "$src" ]; then mkdir -p "$dst"; else mkdir -p "$(dirname "$dst")"; touch "$dst"; fi
        mount --bind "$src" "$dst"
    fi
}

# --- E. BUILD A MINIMAL /etc FOR THE SANDBOX ---
mount_ro /etc/ssl
mount_ro /etc/pki
mount_ro /etc/ca-certificates

# --- F. AUTOMATICALLY MOUNT CURRENT DIRECTORY ---
# The CURRENT_DIR variable is exported by the launcher script.
if [ -n "${CURRENT_DIR:-}" ]; then
    mount_rw "$CURRENT_DIR"
fi

# --- G. USER-DEFINED MOUNTS ---
# Execute user-defined mount commands injected via template.
eval "${PYSANDBOXES_MOUNTS:-}"

# --- H. MOUNT PSEUDO-FILESYSTEMS ---
mount -t tmpfs -o mode=755,nosuid none "$NEW_ROOT/dev"
for dev in null zero full random urandom tty; do
    if [ -e "/dev/$dev" ]; then
        touch "$NEW_ROOT/dev/$dev"
        mount --bind "/dev/$dev" "$NEW_ROOT/dev/$dev"
    fi
done
mkdir -p "$NEW_ROOT/dev/shm"
mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs "$NEW_ROOT/dev/shm"

# Mount the named pipe if it is provided.
if [ -n "${PYSANDBOXES_NAMED_PIPE:-}" ]; then
    PIPE_DIR=$(dirname "$PYSANDBOXES_NAMED_PIPE")
    mkdir -p "$NEW_ROOT$PIPE_DIR"
    touch "$NEW_ROOT$PYSANDBOXES_NAMED_PIPE"
    mount --bind "$PYSANDBOXES_NAMED_PIPE" "$NEW_ROOT$PYSANDBOXES_NAMED_PIPE"
fi

# --- I. UNIFIED DNS/HOSTS SETUP ---
SOURCE_RESOLV_CONF=""
SOURCE_HOSTS=""

if [ -n "${DNS_SERVER:-}" ]; then
    # Case 1: Custom DNS is provided. Create a new resolv.conf.
    SOURCE_RESOLV_CONF=$(mktemp)
    read -r -a dns_array <<< "$DNS_SERVER"
    for dns in "${dns_array[@]}"; do
        echo "nameserver $dns" >> "$SOURCE_RESOLV_CONF"
    done

    SOURCE_HOSTS=$(mktemp)
    echo "127.0.0.1 localhost" > "$SOURCE_HOSTS"
    if [ -n "${PYSANDBOXES_HOSTS:-}" ]; then
        echo "${PYSANDBOXES_HOSTS}" | tr ";" "\n" >> "$SOURCE_HOSTS"
    fi
else
    # Case 2: No custom DNS. Use the host's configuration.
    # Resolve symlinks to get the actual file (e.g. systemd-resolved stub).
    SOURCE_RESOLV_CONF=$(readlink -f "/etc/resolv.conf" 2>/dev/null || echo "/etc/resolv.conf")
    SOURCE_HOSTS=$(readlink -f "/etc/hosts" 2>/dev/null || echo "/etc/hosts")
fi

# Helper: ensure target path exists for bind mounting.
# If target is a symlink (e.g. from bind-mounted /etc), create the file
# at the symlink's destination so it resolves correctly.
ensure_mount_target() {
    local target="$1"
    if [ -L "$target" ]; then
        # Symlink (possibly broken). Create the file it points to.
        local link_target
        link_target=$(readlink "$target")
        local resolved
        if [ "${link_target:0:1}" = "/" ]; then
            resolved="$NEW_ROOT$link_target"
        else
            resolved=$(realpath -s -m "$(dirname "$target")/$link_target")
        fi
        mkdir -p "$(dirname "$resolved")"
        touch "$resolved"
    elif [ ! -e "$target" ]; then
        mkdir -p "$(dirname "$target")"
        touch "$target"
    fi
}

# Mount the chosen configuration files into the chroot.
if [ -n "$SOURCE_RESOLV_CONF" ] && [ -e "$SOURCE_RESOLV_CONF" ]; then
    ensure_mount_target "$NEW_ROOT/etc/resolv.conf"
    mount --bind "$SOURCE_RESOLV_CONF" "$NEW_ROOT/etc/resolv.conf"
fi
if [ -n "$SOURCE_HOSTS" ] && [ -e "$SOURCE_HOSTS" ]; then
    ensure_mount_target "$NEW_ROOT/etc/hosts"
    mount --bind "$SOURCE_HOSTS" "$NEW_ROOT/etc/hosts"
fi

# --- J. ENTER SANDBOX (STAGE 2: PID Namespace & Chroot) ---
ORIGINAL_CWD="$CURRENT_DIR"
cd "$NEW_ROOT"

# Execute the command in the new root, dropping capabilities.
exec /usr/bin/unshare -p -f \
  --mount-proc="$NEW_ROOT/proc" \
  $(which chroot) "$NEW_ROOT" \
  /usr/bin/bash -c "cd \"$ORIGINAL_CWD\"; \
  exec $(which setpriv) --inh-caps=-all --bounding-set=-all -- \
  \"\$@\"" -- "$@"
