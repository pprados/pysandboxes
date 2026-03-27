# Unshare

Unshare/slirp4netns is a user-space container technology that allows programs to be launched in isolation from the rest of the system, with a **user stack IP**. It enables limiting disk access, network access, system calls, and more. For more information, consult the [documentation](https://man7.org/linux/man-pages/man2/unshare.2.html).

Root privileges are not required to add firewall rules.

## Prerequisites

To use the unshare technology, you must install [slirp4netns](https://manpages.debian.org/experimental/slirp4netns/slirp4netns.1.en.html) and set `kernel.unprivileged_userns_clone` to `1`.

```bash
# Check permissions
sysctl kernel.unprivileged_userns_clone
sysctl kernel.apparmor_restrict_unprivileged_userns

# Set permissions
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
sudo sysctl -w kernel.unprivileged_userns_clone=1

# Install slirp4netns
sudo apt install slirp4netns
```

## Execution Model

During launch, a local `root` user within the sandbox is used for code execution. This user has no privileges once directory mounts and iptables rules have been activated.

> **Note:** Some applications may behave differently when running as the 'root' user.