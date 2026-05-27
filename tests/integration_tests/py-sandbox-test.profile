include "./.local.py-sandboxes"  # May be add to .gitignore

py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
bwrap.share-net=yes  # Use host network so bwrap works without root (iptables/slirp need cap_net_admin)
env=TERM=${TERM}
env=My_ENV=${My_ENV}

python-import=*

# tst_usage.py lines 126, 465, 467 call signal.signal(). CPython's
# signal.signal() is a pure-Python wrapper that delegates to the C
# builtin _signal.signal(), so both names are guarded doors on this
# one call; both are needed, or the call fails on the second door.
# Delete when those calls are removed.
python-api=ALLOW:signal.signal,_signal.signal

expose-rw=./tmp
expose-ro=.
expose-ro=/etc
# expose-ro=/run,/run


net=ALLOW|TCP|0.0.0.0/32|50983|IN
net=ALLOW|TCP|ip6-localhost|9999,0|IN
net=ALLOW|TCP|localhost|9999|IN
net=ALLOW|TCP|www.google.com|80|OUT
net=ALLOW|UDP|ip6-localhost|12345|OUT
net=ALLOW|UDP|localhost|12345|IN
net=ALLOW|UDP|localhost|12346,12345|OUT
net=ALLOW|*|*|53|*

ignore=.env

# qemu.use_kvm=true
# qemu.memory=2G
# qemu.virtfs=auto
# qemu.show_boot_console=true
