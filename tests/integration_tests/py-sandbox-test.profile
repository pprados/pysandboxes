include "./.local.py-sandboxes"  # May be add to .gitignore

py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
bwrap.share-net=yes  # Use host network so bwrap works without root (iptables/slirp need cap_net_admin)
env=TERM=${TERM}
env=My_ENV=${My_ENV}

python-import=*

# tst_usage caps blocking NSS lookups with a worker thread
# (_network_dns_result): NSS can hang for minutes in nested QEMU.
# One call crosses several guarded doors. The private start primitive
# is spelled _start_new_thread up to 3.12 and _start_joinable_thread
# from 3.13; both are listed so the profile stays portable, and the
# guard patches only the applicable one.
python-api=ALLOW:threading.Thread.start,threading._start_new_thread,threading._start_joinable_thread

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
