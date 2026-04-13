# OpenMemory Guide — pysandboxes

## User Defined Namespaces

- (Leave blank — user populates)

## Overview

Layered sandbox framework with Python guards and OS-level providers (unshare/bwrap, QEMU).

- **`python_sb` VM path:** Host launch (temp prefix, `launch_args` without `--_named-pipe` append, guest `exitcode` read) uses **`isinstance(os_provider, VMSSEDaemon)`** — not `os_sandbox == "qemu"` — so additional VM hypervisors can share the same branch. **`VMSSEDaemon`** (`vm_sse_daemon.py`) holds shared hooks: `host_run_temp_prefix`, `guest_run_dir_mount`, `augment_rules_for_guest_run_mount`, `show_boot_console_truthy`, `wait_process_and_filter_console`, `read_guest_exitcode`; **`QemuSSEDaemon`** implements them (QEMU-specific bits stay in `qemu_setup` / `qemu_sse_daemon`). **`main_sandbox`** imports `PYTHON_OUTPUT_*` sentinels from **`vm_sse_daemon`**, not `python_sb`.

- **Security audit skill (Cursor):** `.cursor/skills/pysandboxes-os-provider-security-audit/` — structured review of OS providers with `py-sandbox=false` (standalone, container, K8s); env, FS, secrets, network/DNS, TOCTOU on config handoff.
- **Samples framework tool demo (Cursor):** `.cursor/skills/samples-framework-tool-demo/` — scaffold new `samples/<name>/` with dedicated uv, Makefile, `pyproject.toml` (`[tool.uv.sources]` pysandboxes editable), README, root package, `tests/`; implement two tools (web fetch + Python exec) via the chosen agent framework’s native tool APIs; no runtime `pysandboxes` dependency until sandbox integration.
- **Typing:** `BaseDaemon.__init__(**kwargs: Any)` — PEP 484 types each keyword value separately; annotating `**kwargs` as `dict[str, Any]` incorrectly required values like `python_args` / `port` to be dicts and broke mypy.
- **Guard `os.scandir`:** `_ScanDirContextManager` must lazy-open the underlying scanner in `__next__` (not only in `__enter__`) so `for x in os.scandir(path)` works like CPython/pytest (`tmp_path` / `make_numbered_dir`).

## Bwrap / Unshare networking (2025)

- **`slirp4netns_common.py`**: Shared slirp4netns watcher, API socket port forwards (`add_hostfwd`), and constants (`SLIRP_GW` 10.0.2.2, `SLIRP_DNS` 10.0.2.3, guest 10.0.2.100, `tap0`).
- **bwrap**: `--share-net` by default; with socket rules (unless `bwrap.share-net=yes` or `bwrap.unshare-net=no`) uses `--unshare-net`, host-side slirp thread keyed by **child PID**, `main_sandbox` uses `wait_network` + netfilter rules including SSE from 10.0.2.2.
- **`tests/integration_tests/remote/test_bwrap.py`:** sets `os_sandbox_params` to `share-net=yes` so the integration test runs without `CAP_NET_ADMIN`/iptables (the default `net=` profile would otherwise require the unshare-net + slirp path).
- **firejail:** With `net=` socket rules, `_firejail_args` adds `--net=<bridge>`; the SSE daemon listens on the jail's **eth0** address, not `127.0.0.1` on the host. `BaseSubProcessDaemon._ping_url` defaults to loopback; `FireJailSSEDaemon` overrides it using `parse_firejail_net_print` (same addressing as `base_url` / `get_firejail_daemon_ip`).
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

- **VM image fetch:** `RUN` invokes `python -m pysandboxes.remote.qemu_fetch_image` (`pysandboxes/remote/qemu_fetch_image.py`). **Python → Ubuntu image:** `qemu_image.PYTHON_VERSION_TO_UBUNTU_IMAGE` maps 3.10–3.14; **22.04–25.04** use `releases/<ver>/release/ubuntu-…-server-cloudimg-{arch}.img`; **3.14** uses **resolute** `https://cloud-images.ubuntu.com/resolute/current/resolute-server-cloudimg-{arch}.img` (default `python3` is 3.14 on that series).
- **mkdir:** use `mkdir -p "${PYSANDBOXES_VM_IMAGES_DIR}"` so Docker/Podman substitute `ENV`. Escaping as `"$${...}"` can break (e.g. wrong path under `set -x`).
- **Stale wheel:** The base image installs `dist/*.whl`. If you only remove `.make-build-image-qemu`, the base layer may still ship an old wheel without new modules. Prefer `make build-image-qemu` after source changes (Make rebuilds `dist/` when `pysandboxes/**/*.py` is newer than `.make-dist`), or `make build-image-clean` / rebuild base explicitly.

## QEMU guest / `remote.tools`

- **`pysandboxes/remote/tools.py`:** `netifaces` is imported **only** inside `get_default_gateway_info()` (lazy). A module-level import pulled the C extension during `_os_sandbox` → daemon imports and could **segfault** in the QEMU guest; nothing on startup needs gateways there.

- **`pysandboxes/remote/daemon_parameters.py`:** `DaemonParameters` NamedTuple lives here with **`AllRules` as a forward reference only** (`TYPE_CHECKING` + quoted annotation). Importing `all_rules` at module level pulled every guard module at `import main_sandbox` time and caused **SIGSEGV** in the QEMU guest; `main_sandbox` also keeps module-level imports minimal (learning / `config_log` / `remote.tools` / `python_in_sb` loaded lazily inside `main()` / `run_server()` / `__main__`).

- **`pysandboxes/_os_sandbox.py`:** `providers_factory` is a lazy `Mapping`: daemon classes are `importlib.import_module`’d on first `providers_factory[name]` access, so the QEMU guest does not load bwrap/firejail/unshare/aiohttp just to parse `main_sandbox`.

- **QEMU guest `activate_sandboxes`:** When running user code in the VM (`python_main_args` set), `main_sandbox` / `run_guest` call `activate_sandboxes(..., rules_provider="none")` so `NoneDaemon` handles `update_rules_and_activate` only. The real profile still has `os_sandbox=qemu`, but we avoid loading `QemuSSEDaemon` / `SubProcessDaemon` (and **aiohttp**) inside the guest.

- **QEMU serial + ANSI colors:** Guest bootstrap exports `TERM=xterm-256color` and `FORCE_COLOR=1` for Rich on ttyS0; after `python_main_args` env allowlisting, `main_sandbox` `setdefault`s those when `guest_run_dir` is set. For `python-sb -m pytest`, `python_in_sb._inject_pytest_color_yes` prepends `--color=yes` (no `PY_COLORS` env).
- **QEMU bootstrap / segfault:** If `python_exe` on cidata names the host interpreter but that path is **not** visible after 9p mounts (mount failed, wrong path), falling back to the **image** Python while `PYTHONPATH` still lists host `site-packages` loads **host-built `.so`** with the **wrong** libc → often **SIGSEGV**. Bootstrap in `qemu_setup.py` now **poweroff** with an explicit error instead of continuing. Ensure 9p mounts succeed (see `[pysandbox-9p]` lines) or rebuild the nocloud ISO after changing `qemu_setup`. The bootstrap script no longer uses `|| true` after `main_sandbox` (that hid real exit codes); it logs `main_sandbox finished with exit code …` then `poweroff`. For guest stderr **`[PYSANDBOX_DIAG]`** breadcrumbs and **faulthandler** after `main()` starts, use **`qemu.show_boot_console=true`** (same as host VM serial / verbose NoCloud); `main_sandbox` reads `show_boot_console` from `process_config.all_rules` (no separate env var).
- **QEMU `python_exe`:** NoCloud stores the resolved host interpreter via `_guest_python_exe_path()` in `qemu_sse_daemon.py`, aligned with Firejail: `follow_links_executable(Path(sys.executable), …)` then the same resolution as `firejail_sse_daemon._follow_links` (`resolve(strict=True)` for symlinks). This avoids recording only `bin/python` when virtio-9p + `mapped-xattr` breaks `[ -f … ]` in the guest. The bootstrap script also tries `readlink -f` if `-f` fails.

## QEMU provider: return code and writes

- **Return code:** `python-sb` with `os_sandbox=qemu` uses a dedicated host directory under `/tmp` (`TemporaryDirectory(prefix=pysandboxes-qemu-, dir=/tmp)`), 9p-mounted at `GUEST_RUN_MOUNT`. `augment_all_rules_for_qemu_run_mount()` prepends an implicit bind so the guest may write `exitcode` there (profile does not list this path). Host reads `exitcode` after QEMU exits (with polling). Bootstrap runs `sync` before `poweroff`.
- **Single `activate_sandboxes` in QEMU guest:** `main_sandbox.main()` applies guest `root_path=Path.cwd()`, restricts `os.environ` to profile keys, then calls `activate_sandboxes` once. `run_guest` must not call `activate_sandboxes` again — a second call runs `tempfile.mkdtemp()` under `/tmp` while file guards are already active → `RuleFileNotFoundError`.
- **Writes visibility:** The VM uses `-snapshot`; the guest cwd is `/tmp/pysandbox_work` (local to VM). Only writes under the 9p mount `/mnt/pysandboxes-src` (host: parent of pysandboxes package) are visible on the host.
- **Container test trace (`tests/containers_tests/test_containers.py::test_container_runtime`):** default parametrization is `none`, `unshare`, `bwrap` (fast). Nested QEMU in Podman is **opt-in**: `CONTAINER_TEST_QEMU=1`. `podman run` timeout defaults to **120s**; override with env **`CONTAINER_RUN_TIMEOUT`** (seconds). Start/end/KVM/heartbeat for each `podman run` are **DEBUG** (quiet under pytest `--log-cli-level=INFO`); timeouts stay **ERROR**. `CONTAINER_TEST_HEARTBEAT_SEC` (default 60, 0=off). Container stdout/stderr stream to the terminal. With QEMU and `qemu.show_boot_console=false`, host output is filtered to lines between `PYTHON_OUTPUT_START/END` until the guest runs; use `qemu.show_boot_console=true` or `wiki/qemu.md` for full boot logs. When `qemu.show_boot_console=true`, **`QemuSSEDaemon`** uses **pipes +** `pysandboxes/remote/qemu_guest_console_io.start_qemu_serial_drain_tasks` (not FD inherit) so VM serial reaches stderr and **`[qemu-serial]`** DEBUG logs. Verbose NoCloud/bootstrap follows `qemu.show_boot_console` (same as VM serial on host): `py-sandbox-test.profile` sets `true`. Routine **QEMU virtio-9p** / ld-closure staging lines in `qemu_sse_daemon.py` are **DEBUG** so nested container runs stay readable.

- **QEMU nested in Podman/Docker:** Overlay-backed `pysb_exec_*` virtio-9p mounts could **SIGSEGV** in the guest; **virtio-9p staging** (default `qemu.virtfs=auto` when `/.dockerenv`, `/.containerenv`, or `container` env; legacy `qemu.virtfs_stage`) copies exec dirs under `temp/virtfs_stage_exec/` on tmpfs before `-virtfs`. See `wiki/qemu.md` (nested QEMU). **`_stage_dynamic_linker_closure`**: **`qemu.ld_closure_libs=full`** runs **`copytree`** of host **`/lib/<triplet>`** + **`/usr/lib/<triplet>`** into `ld_closure_fs` **before** per-path **`ldd`** copies, and skips **`ldd`** entries under those trees (avoids EEXIST: followed **`copy2`** vs host symlinks). Then PT_INTERP under **`/lib64`**. **`sparse`** keeps only **`ldd`** + small compat `.so` seeds. Guest mount paths follow **`platform.machine()`** (e.g. `x86_64-linux-gnu`).

- **Build one provider:** `make build-image-qemu`, `make build-image-unshare`, etc. (base is built first via Make deps).
- **Build all:** `make build-images` or `make build-image` (alias). **`build-image-docker`** and **`build-image-podman`** are aliases of `build-images` (use after `eval $(minikube docker-env)` so `docker` targets minikube’s daemon).
- **Kubernetes pod test (`test_container_kubernetes`):** **`all_kubernetes_os_sandbox`** = **unshare** + **qemu**. QEMU uses the same integration profile; **`-enable-kvm`** only when **`/dev/kvm`** is available. Exec timeouts: **`K8S_QEMU_EXEC_TIMEOUT`** (qemu, default 900s), **`TIMEOUT`** (unshare, default 120s). **`kubectl exec`** for **`tst_usage`** inherits **stdout/stderr** (no **`capture_output`** / pipes) so nested QEMU does not deadlock on full buffers; **`CONTAINER_TEST_HEARTBEAT_SEC`** (default 60) prints **`[k8s-test]`** lines to **stderr** every N seconds (plus DEBUG) so long QEMU/TCG silence does not look like a hang. **`kubectl logs`**: UTF-8 with **`errors=replace`**. **`minikube mount`**: **`start_new_session=True`** + **`killpg`**. **`kubectl delete pod`**: 120s subprocess timeout. If `make build-image-docker` was a no-op, **ErrImageNeverPull** (`imagePullPolicy: Never`).
- **Container tests** select image from OS_SANDBOX via `_image_for_os_provider()` (e.g. `python-sb-unshare:latest`, `python-sb-qemu:latest`). Keep `pytest.param("none", …)` in `all_os_sandbox`: it exercises the base image quickly; removing it leaves only QEMU (slow in nested Podman, easy to hit `CONTAINER_RUN_TIMEOUT`).
