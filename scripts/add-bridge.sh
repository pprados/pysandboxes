#!/usr/bin/env bash
set -euo pipefail

BRIDGE_NAME=${1:-br0}
BRIDGE_ADDRESS=10.10.20.1/24
BRIDGE_SUBNET=10.10.20.0/24

if [[ ! $BRIDGE_NAME =~ ^[a-zA-Z0-9_.-]{1,15}$ ]]; then
    echo "Invalid bridge name: $BRIDGE_NAME" >&2
    exit 2
fi

if [[ $EUID -ne 0 ]]; then
    exec sudo "$0" "$BRIDGE_NAME"
fi

DEFAULT_INTERFACE=$(ip -4 route show default | awk 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')
if [[ -z $DEFAULT_INTERFACE ]]; then
    echo "Cannot detect the default IPv4 route interface" >&2
    exit 1
fi

if ip link show dev "$BRIDGE_NAME" >/dev/null 2>&1; then
    if ! ip -d link show dev "$BRIDGE_NAME" | grep -q 'bridge'; then
        echo "$BRIDGE_NAME exists but is not a Linux bridge" >&2
        exit 1
    fi
else
    ip link add name "$BRIDGE_NAME" type bridge
fi

if ! ip -4 address show dev "$BRIDGE_NAME" | grep -qF "${BRIDGE_ADDRESS%/*}"; then
    if ip -4 address show dev "$BRIDGE_NAME" | grep -q 'inet '; then
        echo "$BRIDGE_NAME already has an unexpected IPv4 address" >&2
        exit 1
    fi
    ip address add "$BRIDGE_ADDRESS" dev "$BRIDGE_NAME"
fi
ip link set dev "$BRIDGE_NAME" up

# Forward only bridge traffic from the sandbox subnet and its established replies.
sysctl -w net.ipv4.ip_forward=1 >/dev/null
iptables -C FORWARD -i "$BRIDGE_NAME" -o "$DEFAULT_INTERFACE" -s "$BRIDGE_SUBNET" -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -i "$BRIDGE_NAME" -o "$DEFAULT_INTERFACE" -s "$BRIDGE_SUBNET" -j ACCEPT
iptables -C FORWARD -i "$DEFAULT_INTERFACE" -o "$BRIDGE_NAME" -d "$BRIDGE_SUBNET" \
    -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -i "$DEFAULT_INTERFACE" -o "$BRIDGE_NAME" -d "$BRIDGE_SUBNET" \
        -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -t nat -C POSTROUTING -o "$DEFAULT_INTERFACE" -s "$BRIDGE_SUBNET" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -o "$DEFAULT_INTERFACE" -s "$BRIDGE_SUBNET" -j MASQUERADE

echo "Bridge $BRIDGE_NAME configured at $BRIDGE_ADDRESS with NAT through $DEFAULT_INTERFACE"
