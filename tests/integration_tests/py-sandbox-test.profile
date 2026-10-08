include? "./.local.py-sandboxes"  # May be add to .gitignore

py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
bwrap.share-net=yes  # The container suite runs this profile; bwrap's filtered network is unverified in a container. remote/test_bwrap*.py cover it on the host
env=TERM=${TERM}
env=My_ENV=${My_ENV}

python-import=*

expose-rw=./tmp
expose-ro=.
# PYSANDBOXES_SYSTEM_ETC is set by the integration conftest on Windows, which has no /etc.
expose-ro=${PYSANDBOXES_SYSTEM_ETC:-/etc}
# Imports resolved *inside* the sandbox read the interpreter's library tree, and
# guard_files has no stdlib exemption. On the host `expose-ro=.` happens to cover
# it (the venv sits in the project); in a container the interpreter is elsewhere,
# so a deferred `import urllib.request` dies as ModuleNotFoundError. Spell it out.
# PYTHON_BASE_PREFIX is set by the integration conftest; a container has /usr/local.
expose-ro=${PYTHON_BASE_PREFIX:-/usr/local}/lib
# expose-ro=/run,/run


net=ALLOW|TCP|0.0.0.0/32|50983|IN
net=ALLOW|TCP|ip6-localhost|9999,0|IN
net=ALLOW|TCP|localhost|9999|IN
net=ALLOW|TCP|github.com|443|OUT
net=ALLOW|UDP|ip6-localhost|12345|OUT
net=ALLOW|UDP|localhost|12345|IN
net=ALLOW|UDP|localhost|12346,12345|OUT
net=ALLOW|*|*|53|*

ignore=.env

# Set by test_usage_with_providers: the "qemu-tcg" row refuses acceleration, so the
# same scenario is covered both on KVM and on emulation -- the latter being what a
# container gets, since it is not given /dev/kvm.
qemu.use_kvm=${QEMU_USE_KVM:-true}
# A hosted runner has no /dev/kvm and emulates slower than the 180s TCG default allows;
# an upper bound only, kept under the 600s the tests give a qemu run.
qemu.start_timeout=420
# qemu.memory=2G
qemu.virtfs=${QEMU_VIRTFS:-auto}  # `on` stages the trees as inside a container
# Off unless asked: set QEMU_SHOW_BOOT_CONSOLE=true to see the guest's own traces,
# which partial mode otherwise sends to /dev/null (e.g. `gh act --env QEMU_SHOW_BOOT_CONSOLE=true`).
qemu.show_boot_console=${QEMU_SHOW_BOOT_CONSOLE:-false}
