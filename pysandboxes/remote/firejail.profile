# See man firejail
#--quiet
--name=firejail-sandbox
--caps.drop=all
# --caps.keep=net_admin
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
--deterministic-daemon_shutdown
--protocol=inet,inet6
--env=PYTHONSTARTUP=
--private-tmp
--noexec=/tmp

# Disable extras FIXME
#--x11=none
--restrict-namespaces
--nogroups
--nonewprivs
--noprinters
--noroot
--nosound
--notv
--nou2f
--novideo
--oom=900
--disable-mnt
--nodvd
--memory-deny-write-execute
--no3d  # Disable 3D hardware acceleration.

#--blacklist=/etc/hosts
#--blacklist=/etc/resolv.conf
# --hosts-file=/dev/null


# *** Limits ***
#--rlimit-as=${FIREJAIL_RELIMIT:=5m}
--rlimit-cpu=${FIREJAIL_CPU:=5}
--rlimit-fsize=${FIREJAIL_FSIZE:=100k}
--rlimit-nproc=${FIREJAIL_NPROC:=10}
--rlimit-nofile=${FIREJAIL_NOFILE:=50}
--rlimit-sigpending=${FIREJAIL_SIGPENDING:=1}
--nice=${NICE:=2}

# *** Network ***
# public DNS servers
# FIXME: via les rules standards
# --dns=1.1.1.1 --dns=4.4.4.4 --dns=8.8.8.8
#--allow-debuggers

# Debug
#--nettrace=firejail-sandbox
#--dnstrace

#--protocol
