# Firejail

**Firejail** is a simple **OS-Sandbox** technology, allowing programs to be launched isolated from the rest of the system. It is possible to limit disk access, network access, system calls, etc. Consult the [documentation](https://man7.org/linux/man-pages/man1/firejail.1.html) for more information.

For security reasons, code running in bwrap cannot access servers present on the host. To allow this communication, it is necessary to add a network bridge, as Docker also does.

## Using with docker/podman
Firejail is not compatible with docker and podman.

## Specific Parameters

Some specific parameters can be added to `.py-sandboxes` for *Firejail*. Parameters of the form `firejail.<xxx>=<yyy>` will be added in the form `--<xxx>=<yyy>` when launching firejail.

**TODO:** You can thus further strengthen security by limiting the system calls authorized by your application. To do this, you need to identify them. We offer a script [extract_strace.sh](https://github.com/pprados/pysandboxes/tree/develop/scripts) to help you.

```
uv run extract_strace.sh <command to start your application>
```

**TODO:** The `extract_strace.sh` script displays the list of system calls of your application. All that remains is to add them to the `bwrap.seccomp=<xxx>` parameter, separated by commas and without spaces.
