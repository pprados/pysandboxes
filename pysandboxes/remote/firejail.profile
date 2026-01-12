# See man firejail
# See /usr/share/doc/firejail/syscalls.txt
--seccomp=mkdir,@debug,@mount,@reboot,@raw-io,@setuid,@keyring
--name=firejail-sandbox
--hostname=firejail-sandbox
--profile=python.profile
"--env=PYTHONSTARTUP="
--caps.drop=all
--noexec=/tmp
--deterministic-shutdown
--protocol=inet,inet6
--rmenv=SDL_GAMECONTROLLERCONFIG
--private-tmp

# Disable extras
--x11=none
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
# Disable 3D hardware acceleration.
--no3d

#--blacklist=/etc/hosts
#--blacklist=/etc/resolv.conf
--hosts-file=/dev/null


# *** Limits ***
# TIME_OUT=5   NPROC=1  NOFILE=10  RLIMIT=2g FSIZE=100k NICE=2
#--rlimit-as=${FIREJAIL_RELIMIT:=2g}
#--rlimit-cpu=${FIREJAIL_CPU:=5}
#--rlimit-fsize=${FIREJAIL_FSIZE:=100k}
#--rlimit-nproc=${FIREJAIL_NPROC:=10}
#--rlimit-nofile=${FIREJAIL_NOFILE:=50}
#--rlimit-sigpending=${FIREJAIL_SIGPENDING:=1}
#--nice=${NICE:=2}

# *** Network ***
# public DNS servers
#--dns=1.1.1.1 --dns=4.4.4.4 --dns=8.8.8.8
#--allow-debuggers

# Debug
#--nettrace=firejail-sandbox
#--dnstrace

#--protocol
# --quiet
#--netfilter=/etc/firejail/tcpserver.net",  # FIXME
