include "./.local.py-sandboxes"  # May be add to .gitignore

py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
bwrap.share-net=yes  # Use host network so bwrap works without root (iptables/slirp need cap_net_admin)
env=TERM=${TERM}
env=My_ENV=${My_ENV}

python-import=*

expose-rw=./tmp
expose-ro=.
expose-ro=/etc
# Imports resolved *inside* the sandbox read the interpreter's library tree, and
# guard_files has no stdlib exemption. On the host `expose-ro=.` happens to cover
# it (the venv sits in the project); in a container the interpreter is elsewhere,
# so a deferred `import requests` dies as ModuleNotFoundError. Spell it out.
expose-ro=/usr/local/lib
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
