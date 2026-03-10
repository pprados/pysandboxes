#!/bin/bash
set -x
DEFAULT_INTERFACE=$(ip route get 8.8.8.8 | awk '/dev/ {print $5; exit}')
BRIDGE_NAME=${1:-br0}
#
# Routed network configuration script
#
ip link set ${BRIDGE_NAME} down
brctl delbr ${BRIDGE_NAME}

# bridge setup
brctl addbr ${BRIDGE_NAME}
ifconfig ${BRIDGE_NAME} 10.10.20.1/24 up

# enable ipv4 forwarding
echo "1" > /proc/sys/net/ipv4/ip_forward

# netfilter cleanup
iptables --flush
iptables -t nat -F
iptables -X
iptables -Z
iptables -P INPUT ACCEPT
iptables -P OUTPUT ACCEPT
iptables -P FORWARD ACCEPT

# netfilter network address translation
iptables -t nat -A POSTROUTING -o ${DEFAULT_INTERFACE} -s 10.10.20.0/24 -j MASQUERADE

echo "Bridge ${BRIDGE_NAME} up and running"
