# Changelog

| Python   | OS-Sandbox   | OS        | Feature   |
|----------|--------------|-----------|-----------|
| ✅ 3.10   | ✅ subprocess | ✅ Linux   | ✅ Env     |
| ✅ 3.11   | ✅ Firejail   | ☐ MacOS   | ✅ Files   |
| ✅ 3.12   | ☐ Docker     | ☐ Windows | ✅ Network |
| ✅ 3.13   | ☐ Podman     |           | ✅ Import  |
| ☐ 3.14   | ☐ qemu       |           | ☐ API     |
|          | ☐ VM         |           | ☐ Source  |
|          |              |           | ☐ Regexp  |
|          |              |           | ☐ DoS     |

## [0.1.0] - 2025-11-27

### Added
- First stable version
- accept *complete* and *selected* mode
- Control environment variables
- Control import list
- Control file and network access
- Control life cycle of the sandbox-daemon (restart if necessary)
- implement `none`, `subprocess` and `firejail` os-sandbox
- MCP client/server samples
