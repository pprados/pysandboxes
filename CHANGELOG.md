# Changelog

| Python   | OS-Sandbox    | OS        | Feature   |
|----------|---------------|-----------|-----------|
| ✅ 3.11   | ✅ none        | ✅ Linux   | ✅ Env     |
| ✅ 3.12   | ✅ subprocess  | ☐ MacOS   | ✅ Files   |
| ✅ 3.13   | ✅ landlock    | ☐ Windows | ✅ Network |
| ✅ 3.14   | ✅ bwrap       |           | ✅ Import  |
|          | ✅ firejail    |           | ✅ API     |
|          | ✅ unshare     |           | ☐ Source  |
|          | ✅ qemu        |           | ☐ Regexp  |
|          | ✅ Docker¹     |           | ☐ DoS     |
|          | ✅ Podman¹     |           |           |
|          | ☐ gVisor      |           |           |
|          | ☐ micro-VM    |           |           |

¹ Docker and Podman are not providers of their own: a container runs the
`unshare` provider, with `--privileged` for Docker.

## [0.0.3] - 2026-10-06

## [0.0.2] - 2026-10-06

### Added
- First stable version
- Accept *complete* and *selected* mode
- Control environment variables
- Control import list
- Control file and network access
- Control life cycle of the sandbox-daemon (restart if necessary)
- Seven OS-sandbox providers, selected with `OS_SANDBOX=` or `--os-sandbox`: `none`, `subprocess`, `landlock`, `bwrap`, `firejail`, `unshare` and `qemu`; Docker and Podman are covered through `unshare`
- Twelve samples, each with its own rules, test suite and interactive chat, covering the main agent frameworks and MCP
- Code that arrives as a string at runtime is guarded by the `eval-*` rules: it is checked against a configurable sub-language and run under a budget and a timeout, without affecting the application's own modules
- Control of sensitive API calls, independent of import rights: sensitive functions are denied by default and granted by category or by function with `python-api=`, and learning mode generates the rules an application needs
- Unpickling is now controlled under a new `deserialization` category

### Fixed
- `posix.chroot` is now guarded with the same path check as `os.chroot`
- Network filtering now works inside the `qemu` container image

### Security
- The `native` and `introspection` categories are detection and friction, not a barrier; the OS sandboxes remain the real barrier
- `pickle.Unpickler` stays unguarded and is documented as such

