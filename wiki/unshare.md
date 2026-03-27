# Unshare

Unshare/slirp4netns is a user container technology, allowing programs to be launched isolated from the rest of the system, with a user stack ip. It is possible to limit disk access, network access, system calls, etc. Consult the [documentation](https://man7.org/linux/man-pages/man2/unshare.2.html) for more information.

To use the unshare technology, you must install [slirp4netns](https://manpages.debian.org/experimental/slirp4netns/slirp4netns.1.en.html), and set `kernel.unprivileged_userns_clone` to `1`.

```bash
# check permission
sysctl kernel.unprivileged_userns_clone
sysctl kernel.apparmor_restrict_unprivileged_userns

# Set permission
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
sudo sysctl -w kernel.unprivileged_userns_clone=1
# Install slirp4netns
sudo apt install slirp4netns
```
