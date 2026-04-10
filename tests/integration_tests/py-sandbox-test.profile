include "./.local.py-sandboxes"  # May be add to .gitignore

py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
bwrap.share-net=yes  # Use host network so bwrap works without root (iptables/slirp need cap_net_admin)
env=TERM=${TERM}
env=My_ENV=${My_ENV}

python-import=*

bind=./tmp,./tmp
ro-bind=.,.
ro-bind=/etc,/etc
# ro-bind=/run,/run


net=ALLOW|TCP|0.0.0.0/32|50983|IN
net=ALLOW|TCP|ip6-localhost|9999,0|IN
net=ALLOW|TCP|localhost|9999|IN
net=ALLOW|TCP|www.google.com|80|OUT
net=ALLOW|UDP|ip6-localhost|12345|OUT
net=ALLOW|UDP|localhost|12345|IN
net=ALLOW|UDP|localhost|12346,12345|OUT
net=ALLOW|*|*|53|*

ignore=.env

qemu.use_kvm=true  # FIXME
qemu.show_boot_console=false