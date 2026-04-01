# Firejail

Firejail is a simple **OS-Sandbox** technology, allowing programs to be launched isolated from the rest of the system. It is possible to limit disk access, network access, system calls, etc. Consult the [documentation](https://man7.org/linux/man-pages/man1/firejail.1.html) for more information.

If you want to use the network within a sandbox, it is preferable to set the `restricted-network no` parameter in the `/etc/firejail/firejail.config` file. Otherwise, only Python rules are applied.

For security reasons, code running in firejail cannot access servers present on the host. To allow this communication, it is necessary to add a network bridge, as Docker also does.

To use the [firejail](https://github.com/netblue30/firejail) technology, you must have a network bridge. Check it with:

```bash
sudo apt install firejail
ip link show type bridge
```

If you find `docker0` or `br0`, it's good.

Otherwise, you must create a bridge. The `[add-bridge.sh](https://github.com/pprados/pysandboxes/tree/master/scripts)` script does this.

```bash
sudo uv run ./add-bridge.sh
```

## Using with docker/podman
Firejail is not compatible with docker and podman.

## Specific Parameters

Some specific parameters can be added to `.py-sandboxes` for *Firejail*. Parameters of the form `firejail.<xxx>=<yyy>` will be added in the form `--<xxx>=<yyy>` when launching firejail.

To force to use a specific bridge, add `--firejail.eth=my_bridge`.

You can thus further strengthen security by limiting the system calls authorized by your application. To do this, you need to identify them. We offer a script [extract_strace.sh](https://github.com/pprados/pysandboxes/tree/develop/scripts) to help you.

```
uv run extract_strace.sh <command to start your application>
```

The `extract_strace.sh` script displays the list of system calls of your application. All that remains is to add them to the `firejail.seccomp=<xxx>` parameter, separated by commas and without spaces.
