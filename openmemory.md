# OpenMemory Guide — pysandboxes

## User Defined Namespaces

- (Leave blank — user populates)

## Overview

Layered sandbox framework with Python guards and OS-level providers (unshare/bwrap, QEMU).

## Docker image variants

One image per OS provider; all are built FROM base. Image **names** are `python-sb-base`, `python-sb-unshare`, `python-sb-bwrap`, `python-sb-qemu`. Each is tagged with **version** (e.g. `3.12`) and **latest**.

| Provider  | Image name       | Dockerfile         | Tags (e.g. Python 3.12)  |
|----------|------------------|--------------------|---------------------------|
| base     | python-sb-base   | Dockerfile         | `3.12`, `latest`         |
| unshare  | python-sb-unshare| Dockerfile-unshare | `3.12`, `latest`         |
| bwrap    | python-sb-bwrap  | Dockerfile-bwrap   | `3.12`, `latest`         |
| qemu     | python-sb-qemu   | Dockerfile-qemu    | `3.12`, `latest`         |

(firejail is not supported in Docker; no image for it.)

## QEMU provider: return code and writes

- **Return code:** When running a script via `python-sb` with `os_sandbox=qemu`, the guest writes its exit code to a file on a 9p-shared run dir (`guest_run_dir`). The host reads `exitcode` from the temp dir after the QEMU process exits and returns that value. Implemented via `DaemonParameters.guest_run_dir`, `RUN_9P_TAG` / `GUEST_RUN_MOUNT` in bootstrap, and writing in `main_sandbox.run_guest` before return.
- **Writes visibility:** The VM uses `-snapshot`; the guest cwd is `/tmp/pysandbox_work` (local to VM). Only writes under the 9p mount `/mnt/pysandboxes-src` (host: parent of pysandboxes package) are visible on the host.

- **Build one:** `make build-image VARIANT=qemu` or `make build-image-unshare`, etc.
- **Build all (docker):** `make build-image-docker` (e.g. for minikube).
- **Container tests** select image from OS_SANDBOX via `_image_for_os_provider()` (e.g. `python-sb:unshare`, `python-sb:qemu`).
