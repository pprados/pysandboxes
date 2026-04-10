# OpenMemory Guide — pysandboxes

## User Defined Namespaces

- (Leave blank — user populates)

## Overview

Layered sandbox framework with Python guards and OS-level providers (unshare/bwrap, QEMU).

## Bwrap / Unshare networking (2025)

- **`slirp4netns_common.py`**: Shared slirp4netns watcher, API socket port forwards (`add_hostfwd`), and constants (`SLIRP_GW` 10.0.2.2, `SLIRP_DNS` 10.0.2.3, guest 10.0.2.100, `tap0`).
- **bwrap**: `--share-net` by default; with socket rules (unless `bwrap.share-net=yes` or `bwrap.unshare-net=no`) uses `--unshare-net`, host-side slirp thread keyed by **child PID**, `main_sandbox` uses `wait_network` + netfilter rules including SSE from 10.0.2.2.
- **unshare**: Daemon launches `unshare` → `unshare_setup` → `main_sandbox`; **no** `unshare_launcher`. Slirp runs on host via pidfile + watcher; JSON setup via FIFO under temp; `PYTHONPATH` set to project root for Docker.

## Docker image variants

**Dependency:** `python:${VER}-slim` → **`python-sb`** (`Dockerfile`, wheel install) → provider images each **`FROM python-sb:${VER}`** (`Dockerfile-landlock`, `-unshare`, `-bwrap`, `-qemu`). Make prerequisites mirror this: `.make-build-image-base` before every provider stamp.

| Role     | Image name         | Dockerfile         | Tags (e.g. Python 3.12)   |
|----------|--------------------|--------------------|---------------------------|
| base     | `python-sb`        | Dockerfile         | `3.12`, `latest`, …     |
| landlock | `python-sb-landlock` | Dockerfile-landlock | `3.12`, `latest`, …   |
| unshare  | `python-sb-unshare` | Dockerfile-unshare | `3.12`, `latest`, …    |
| bwrap    | `python-sb-bwrap`  | Dockerfile-bwrap   | `3.12`, `latest`, …      |
| qemu     | `python-sb-qemu`   | Dockerfile-qemu    | `3.12`, `latest`, …      |

(firejail is not supported in Docker; no image for it.)

### QEMU image build (`Dockerfile-qemu`)

- **VM image fetch:** `RUN` invokes `python -m pysandboxes.remote.qemu_fetch_image` (`pysandboxes/remote/qemu_fetch_image.py`).
- **mkdir:** use `mkdir -p "${PYSANDBOXES_VM_IMAGES_DIR}"` so Docker/Podman substitute `ENV`. Escaping as `"$${...}"` can break (e.g. wrong path under `set -x`).
- **Stale wheel:** The base image installs `dist/*.whl`. If you only remove `.make-build-image-qemu`, the base layer may still ship an old wheel without new modules. Prefer `make build-image-qemu` after source changes (Make rebuilds `dist/` when `pysandboxes/**/*.py` is newer than `.make-dist`), or `make build-image-clean` / rebuild base explicitly.

## QEMU guest / `remote.tools`

- **`pysandboxes/remote/tools.py`:** `netifaces` is imported **only** inside `get_default_gateway_info()` (lazy). A module-level import pulled the C extension during `_os_sandbox` → daemon imports and could **segfault** in the QEMU guest; nothing on startup needs gateways there.

- **`pysandboxes/remote/daemon_parameters.py`:** `DaemonParameters` NamedTuple lives here with **`AllRules` as a forward reference only** (`TYPE_CHECKING` + quoted annotation). Importing `all_rules` at module level pulled every guard module at `import main_sandbox` time and caused **SIGSEGV** in the QEMU guest; `main_sandbox` also keeps module-level imports minimal (learning / `config_log` / `remote.tools` / `python_in_sb` loaded lazily inside `main()` / `run_server()` / `__main__`).

- **`pysandboxes/_os_sandbox.py`:** `providers_factory` is a lazy `Mapping`: daemon classes are `importlib.import_module`’d on first `providers_factory[name]` access, so the QEMU guest does not load bwrap/firejail/unshare/aiohttp just to parse `main_sandbox`.

- **QEMU guest `activate_sandboxes`:** When running user code in the VM (`python_main_args` set), `main_sandbox` / `run_guest` call `activate_sandboxes(..., rules_provider="none")` so `NoneDaemon` handles `update_rules_and_activate` only. The real profile still has `os_sandbox=qemu`, but we avoid loading `QemuSSEDaemon` / `SubProcessDaemon` (and **aiohttp**) inside the guest.

- **QEMU bootstrap / segfault:** If `python_exe` on cidata names the host interpreter but that path is **not** visible after 9p mounts (mount failed, wrong path), falling back to the **image** Python while `PYTHONPATH` still lists host `site-packages` loads **host-built `.so`** with the **wrong** libc → often **SIGSEGV**. Bootstrap in `qemu_setup.py` now **poweroff** with an explicit error instead of continuing. Ensure 9p mounts succeed (see `[pysandbox-9p]` lines) or rebuild the nocloud ISO after changing `qemu_setup`. The bootstrap script no longer uses `|| true` after `main_sandbox` (that hid real exit codes); it logs `main_sandbox finished with exit code …` then `poweroff`. For deep guest traces set `PYSANDBOXES_GUEST_DIAG=1` (stderr breadcrumbs + faulthandler in `main_sandbox`).
- **QEMU `python_exe`:** NoCloud stores the resolved host interpreter via `_guest_python_exe_path()` in `qemu_sse_daemon.py`, aligned with Firejail: `follow_links_executable(Path(sys.executable), …)` then the same resolution as `firejail_sse_daemon._follow_links` (`resolve(strict=True)` for symlinks). This avoids recording only `bin/python` when virtio-9p + `mapped-xattr` breaks `[ -f … ]` in the guest. The bootstrap script also tries `readlink -f` if `-f` fails.

## QEMU provider: return code and writes

- **Return code:** `python-sb` with `os_sandbox=qemu` uses a dedicated host directory under `/tmp` (`TemporaryDirectory(prefix=pysandboxes-qemu-, dir=/tmp)`), 9p-mounted at `GUEST_RUN_MOUNT`. `augment_all_rules_for_qemu_run_mount()` prepends an implicit bind so the guest may write `exitcode` there (profile does not list this path). Host reads `exitcode` after QEMU exits (with polling). Bootstrap runs `sync` before `poweroff`.
- **Single `activate_sandboxes` in QEMU guest:** `main_sandbox.main()` applies guest `root_path=Path.cwd()`, restricts `os.environ` to profile keys, then calls `activate_sandboxes` once. `run_guest` must not call `activate_sandboxes` again — a second call runs `tempfile.mkdtemp()` under `/tmp` while file guards are already active → `RuleFileNotFoundError`.
- **Writes visibility:** The VM uses `-snapshot`; the guest cwd is `/tmp/pysandbox_work` (local to VM). Only writes under the 9p mount `/mnt/pysandboxes-src` (host: parent of pysandboxes package) are visible on the host.
- **Container test trace (`tests/containers_tests/test_containers.py::test_container_runtime`):** container stdout/stderr are streamed to the terminal by default (no temp file, no flags). With QEMU and `qemu.show_boot_console=false`, host output is filtered to lines between `PYTHON_OUTPUT_START/END` until the guest runs; use `qemu.show_boot_console=true` or `wiki/qemu.md` for full boot logs.

- **Build one provider:** `make build-image-qemu`, `make build-image-unshare`, etc. (base is built first via Make deps).
- **Build all:** `make build-images` or `make build-image` (alias). For minikube Docker daemon, docs refer to `make build-image-docker` if defined.
- **Container tests** select image from OS_SANDBOX via `_image_for_os_provider()` (e.g. `python-sb:unshare`, `python-sb:qemu`).
