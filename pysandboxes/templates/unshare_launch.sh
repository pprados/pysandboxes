#!/bin/bash

# Exit on error, undefined variables, and pipe failures
set -euo pipefail

# --- CONFIGURATION ---
INTERFACE="tap0"
export PID_FILE=$(mktemp) # Used by unshare_setup.sh to signal readiness
SLIRP_PID_FILE=$(mktemp)  # Used by slirp4netns to find the child process
API_SOCKET=$(mktemp -u)    # API socket path for slirp4netns port forwarding

# Export variables for the setup script.
export DNS_SERVER="${PYSANDBOXES_DNS:-}"

# Check if arguments are provided
if [ $# -lt 2 ]; then
    echo "Usage: $0 <setup_script> [unshare_flags...] -- <command> [args...]"
    exit 1
fi

SETUP_SCRIPT="$1"
shift

# Parse arguments to separate unshare flags and command
ARGS=("$@")
UNSHARE_FLAGS=()
COMMAND_ARGS=()
FOUND_SEP=0

for arg in "${ARGS[@]}"; do
    if [ "$FOUND_SEP" -eq 1 ]; then
        COMMAND_ARGS+=("$arg")
    elif [ "$arg" == "--" ]; then
        FOUND_SEP=1
    else
        UNSHARE_FLAGS+=("$arg")
    fi
done

if [ "$FOUND_SEP" -eq 0 ]; then
    # No separator found. Assume old behavior: default flags, all args are command.
    UNSHARE_FLAGS=(-r -n -m)
    COMMAND_ARGS=("${ARGS[@]}")
fi

# Resolve the command to an absolute path, following symlinks
if [ ${#COMMAND_ARGS[@]} -gt 0 ]; then
    CMD="${COMMAND_ARGS[0]}"
    if command -v "$CMD" >/dev/null 2>&1; then
        RESOLVED=$(readlink -f "$(which "$CMD")")
        COMMAND_ARGS[0]="$RESOLVED"
    fi
fi

# --- 1. SLIRP4NETNS BACKGROUND PROCESS ---
# This block runs in the background to configure networking for the unshared process.
# The --api-socket enables runtime port forwarding from host to sandbox.
exec 3< <(
    while [ ! -s "$SLIRP_PID_FILE" ]; do sleep 0.05; done
    CHILD_PID=$(cat "$SLIRP_PID_FILE")
    # Configure slirp4netns with MTU 1500, ready-fd 4, and API socket for port forwarding
    exec slirp4netns -c -m 1500 -r 4 --api-socket "$API_SOCKET" "$CHILD_PID" "$INTERFACE" 4>&1 2>/dev/null
)
# --- 2. LAUNCH UNSHARE (STAGE 1: Network & User Namespace) ---
if [ ! -f "$SETUP_SCRIPT" ]; then
    echo "Error: Setup script not found or not executable at $SETUP_SCRIPT"
    exit 1
fi

# Save stdin before backgrounding (background processes get /dev/null as stdin)
exec 4<&0
# Start unshare in background to get its PID.
# It will execute the setup script which waits for network configuration.
unshare "${UNSHARE_FLAGS[@]}" 3<&3 0<&4 /usr/bin/bash "$SETUP_SCRIPT" "${COMMAND_ARGS[@]}" &
UNSHARE_PID=$!

exec 4<&-

# Write PID to SLIRP_PID_FILE so slirp4netns can attach
echo "$UNSHARE_PID" > "$SLIRP_PID_FILE"

# --- 2.5. SET UP PORT FORWARDING ---
# If PYSANDBOXES_PORT is set, forward host:PORT -> sandbox 10.0.2.100:PORT
# This allows the host to reach the FastAPI server inside the network namespace.
if [ -n "${PYSANDBOXES_PORT:-}" ]; then
    # Wait for API socket to be created by slirp4netns (timeout ~5s)
    _timeout=50
    while [ ! -S "$API_SOCKET" ] && [ $_timeout -gt 0 ]; do
        sleep 0.1
        _timeout=$((_timeout - 1))
    done
    if [ -S "$API_SOCKET" ]; then
        python3 -c "
import socket, json, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(sys.argv[1])
cmd = json.dumps({
    'execute': 'add_hostfwd',
    'arguments': {
        'proto': 'tcp',
        'host_addr': '127.0.0.1',
        'host_port': int(sys.argv[2]),
        'guest_addr': '10.0.2.100',
        'guest_port': int(sys.argv[2])
    }
})
s.sendall(cmd.encode() + b'\0')
s.recv(4096)
s.close()
" "$API_SOCKET" "$PYSANDBOXES_PORT" 2>/dev/null || true
    fi
fi

# Wait for unshare to finish
set +e
wait "$UNSHARE_PID"
EXIT_CODE=$?
set -e

# --- 3. CLEANUP ---
rm -f "$PID_FILE" "$SLIRP_PID_FILE" "$API_SOCKET"
# Kill any remaining child processes
pkill -P $$ || true
exit "$EXIT_CODE"
