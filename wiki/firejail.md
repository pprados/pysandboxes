To use the [firejail](https://github.com/netblue30/firejail) technology, you must have a network bridge. Check-it with:
```bash
ip link show type bridge
```
If you find `docker0` or `br0`, it's cool.

Else, you must create a bridge with:
```bash
sudo apt update
sudo apt install bridge-utils
sudo ip link add name br0 type bridge
sudo ip addr add 10.10.10.1/24 dev br0
sudo ip link set br0 up

sudo sysctl -w net.ipv4.ip_forward=1
DEFAULT_INTERFACE=$(ip route get 8.8.8.8 | awk '/dev/ {print $5; exit}')
sudo iptables -t nat -A POSTROUTING -o ${DEFAULT_INTERFACE} -j MASQUERADE
```
#TODO: pour
sudo iptables -t nat -A PREROUTING -i docker0 -p udp --dport 53 -j DNAT --to-destination 192.168.0.99