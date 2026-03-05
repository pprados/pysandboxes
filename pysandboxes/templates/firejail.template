# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
# See man firejail
#--quiet
--caps.drop=all
#--private # Any files created in this directory will be deleted when you daemon_shutdown the sandbox
--noprofile
--include=/etc/firejail/allow-python3.inc
--include=/etc/firejail/disable-common.inc
--include=/etc/firejail/disable-devel.inc
--include=/etc/firejail/disable-interpreters.inc
--include=/etc/firejail/disable-programs.inc
--include=/etc/firejail/disable-xdg.inc
# See /usr/share/doc/firejail/syscalls.txt
# --seccomp=mkdir,@debug,@mount,@reboot,@raw-io,@setuid,@keyring
--hostname=firejail-sandbox
--deterministic-shutdown
--protocol=inet,inet6
--env=PYTHONSTARTUP=
# --private-dev
# --private-tmp
# --noexec=/tmp

# Disable extras
# --restrict-namespaces
# --nogroups
# --nonewprivs
# --noprinters
# --noroot

# --x11=none
# --nosound
# --notv
# --nou2f
# --novideo
# --nodvd
# --disable-mnt
# --no3d  # Disable 3D hardware acceleration.

# *** Limits ***
# --rlimit-as=${FIREJAIL_RELIMIT:-300m}
# --rlimit-fsize=${FIREJAIL_FSIZE:-102400}
# --rlimit-nproc=${FIREJAIL_NPROC:-20}
# --rlimit-nofile=${FIREJAIL_NOFILE:-50}
# --rlimit-sigpending=${FIREJAIL_SIGPENDING:-20}
# --nice=${NICE:-5}

# Debug
#--allow-debuggers
#--nettrace=firejail-sandbox
#--dnstrace

#--protocol
