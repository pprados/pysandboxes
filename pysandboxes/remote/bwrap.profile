# See man bwrap
#--share-net
--die-with-parent
--argv0 python
--clearenv
--setenv PYTHONSTARTUP ""
--setenv PATH "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
--setenv TEMP "/tmp"
--setenv TMP "/tmp"
--dir /tmp

## Extra
#--unshare-all
## or
#--unshare-user
#--unshare-ipc
#--unshare-pid
#--unshare-net
#--unshare-uts

# --chdir DIR


--ro-bind /etc/resolv.conf /etc/resolv.conf


#--dev /dev
#--proc /proc
#--ro-bind /usr/lib/python3.12/encodings /usr/local/lib/python3.12/encodings
#--dir /var
#--ro-bind /usr /usr
#--ro-bind /etc /etc
