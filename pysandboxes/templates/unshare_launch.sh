#!/bin/bash
# Configuration
INTERFACE="tap0"
PID_FILE=$(mktemp)

# Check if arguments are provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <command> [args...]"
    exit 1
fi

# 1. Background synchronization for slirp4netns
exec 3< <(
    while [ ! -s "$PID_FILE" ]; do sleep 0.05; done
    CHILD_PID=$(cat "$PID_FILE")
    
    # -r 4: Signal readiness to FD 4
    # -c: automatically configure the tap interface
    exec slirp4netns -c -m 1500 -r 4 "$CHILD_PID" "$INTERFACE" 4>&1 2>/dev/null
)

# 2. Launch unshare with Network and User namespaces
# -r: map-root-user
# -n: network namespace
# -m: mount namespace (required for chroot)
# Pass FD 3 to the unshare environment
unshare -r -n -m bash 3<&3 -c '
    # Register PID for slirp4netns
    echo $$ > "'"$PID_FILE"'"
    
    # Wait for network readiness signal
    read -n 1 -u 3
    
    # Network setup
    ip link set lo up
    
    # Configure DNS (slirp4netns DNS is at 10.0.2.3)
    mkdir -p /tmp/sandbox_etc
    mount --bind /tmp/sandbox_etc/resolv.conf /etc/resolv.conf
    
    # Enter the chroot environment
    exec "$@"
' -- "$@"

# 3. Cleanup
rm "$PID_FILE"
pkill -P $$
