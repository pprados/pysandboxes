# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""QEMU-based VM SSE daemon for PySandboxes.

Runs the sandbox inside a QEMU VM. Uses -net user + hostfwd for SSE.
Virtio-9p exposes file_rules root at /app (same strategy as bwrap) and
the run dir (named pipe for config) at /mnt/pysandbox_run. Guest runs
main_sandbox --_named-pipe to read config from the pipe.
"""

import asyncio
import gc
import logging
import os
import pickle
import platform
import re
import shutil
import site
import subprocess
import sys
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, Mapping

from ..all_rules import AllRules
from ..config import DEBUG
from ..guard_files import FSExposeRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..netfilter import rule_to_netfilter
from ..override_compat import override
from ..sb_types import Args, ConfigLines, Envs
from ..tools import Environ, follow_links_executable
from .client_subprocess_sse_daemon import (
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .daemon_parameters import DaemonParameters
from .parameters import (
    INTERVAL_FOR_PING_DAEMON,
    TIMEOUT_FOR_PING,
)
from .qemu_guest_console_io import start_qemu_serial_drain_tasks
from .qemu_image import (
    ensure_image,
    get_default_image_path,
    is_kvm_available,
    normalize_qemu_m_memory_arg,
)
from .qemu_setup import (
    GUEST_CONFIG_MOUNT,
    GUEST_RUN_MOUNT,
    QEMU_HOST_RUN_PREFIX,
    augment_all_rules_for_qemu_run_mount,
    prepare_guest_env,
)
from .tools import is_transient_connection_error, which_command
from .vm_sse_daemon import VMSSEDaemon

# VM boot + cloud-init can take 20–40s before main_sandbox listens; wait before pinging.
QEMU_BOOT_DELAY = 20.0
# Allow more ping attempts after boot (VM is slower than a subprocess).
QEMU_LOOP_FOR_PING = 200

logger = logging.getLogger(__name__)

# When True, config is written under ./tmp/pysb_config for inspection; else use named pipe to avoid race.
DEBUG_CONFIG = DEBUG or False


def _guest_python_exe_path() -> str:
    """Resolved host interpreter for NoCloud ``python_exe`` (Firejail-aligned).

    ``firejail_sse_daemon.subprocess_cmd`` uses ``follow_links_executable(Path(sys.executable), …)``
    then ``_follow_links``, which records ``Path(filename).resolve(strict=True)`` when the launcher
    is a symlink. We walk the same chain, then return the resolved path so the QEMU guest sees a
    real ELF via virtio-9p (conda ``bin/python`` → ``python3.13`` is a common case).
    """
    exe = Path(sys.executable)
    bin_path: set[Path] = set()
    follow_links_executable(exe, bin_path)
    _bin_paths_include_resolved_interpreter(exe, bin_path)
    try:
        for p in bin_path:
            if p.is_file():
                return str(p.resolve(strict=True))
        if exe.is_symlink():
            return str(exe.resolve(strict=True))
        return str(exe.resolve(strict=True))
    except FileNotFoundError as e:
        raise RuntimeError("Impossible to resolve the sys.executable `%s`", sys.executable) from e


def _bin_paths_include_resolved_interpreter(executable: Path, bin_paths: set[Path]) -> None:
    """Register the resolved interpreter file when ``follow_links_executable`` no-ops.

    That helper returns immediately for ``/usr/bin`` and ``/usr/local/bin`` to avoid
    treating ``<prefix>/bin/python`` as a venv-style layout (which would add ``/usr`` or
    ``/usr/local`` as a single mount). Without a concrete file in ``bin_paths``, QEMU
    never stages ``<prefix>/lib`` (``libpython*.so*``) next to Docker's ``python3.X``.
    """
    try:
        exr = executable.resolve(strict=True)
        if exr.is_file():
            bin_paths.add(exr)
    except OSError:
        pass


def _add_dir_follow_links(path: Path, out: set[Path]) -> None:
    """Add resolved directory to set (follow symlinks, firejail-style). Skip /usr/lib."""
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return
    if str(resolved).startswith("/usr/lib"):
        return
    dir_path = resolved if resolved.is_dir() else resolved.parent
    out.add(dir_path)


def _norm_guest_path(guest_path: str) -> str:
    """Canonical guest mount key so ``/app`` and ``/app/`` dedupe."""
    return os.path.normpath(guest_path)


def _running_in_container() -> bool:
    """True if likely inside Docker/Podman/OCI (used for virtio-9p staging default)."""
    if Path("/.dockerenv").is_file():
        return True
    if Path("/.containerenv").is_file():
        return True
    return bool(os.environ.get("container"))


def _virtfs_staging_mode(os_sandbox_params: Mapping[str, Any]) -> str:
    """Return normalized ``qemu.virtfs`` mode: ``auto`` | ``on`` | ``off``.

    Default ``auto``. Empty / whitespace-only values are treated as ``auto``.
    ``qemu.virtfs_stage`` is a legacy alias when ``qemu.virtfs`` is unset.
    """
    if "virtfs" in os_sandbox_params:
        v = os_sandbox_params["virtfs"]
        s = "" if v is None else str(v).strip().lower()
        return "auto" if not s else s
    if "virtfs_stage" in os_sandbox_params:
        v = os_sandbox_params["virtfs_stage"]
        s = "" if v is None else str(v).strip().lower()
        return "auto" if not s else s
    return "auto"


def _virtfs_stage_exec_needed(os_sandbox_params: Mapping[str, Any]) -> bool:
    """Whether to copy Python exec dirs to temp before -virtfs (overlay + 9p mmap SIGSEGV workaround).

    Controlled by ``qemu.virtfs=auto|on|off`` (default auto). Legacy: ``qemu.virtfs_stage``.
    """
    raw = _virtfs_staging_mode(os_sandbox_params)
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("auto",):
        return _running_in_container()
    logger.warning(
        "Unknown qemu.virtfs value %r; using auto (container-detected staging)",
        raw,
    )
    return _running_in_container()


_VIRTFS_STAGE_SKIP_DIR_NAMES = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        ".git",
        ".cursor",
        ".claude",
        ".codex",
        ".vscode",
        ".vs",
        ".github",
        "_bmad",
        ".ia_backup",
        ".idea",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        ".tox",
        ".nox",
        "dist",
        "build",
        # Nested sample venvs + odd files break overlay/minikube 9p (errno 526); not needed for package imports.
        "samples",
        "docs",
        ".svn",
        ".hg",
    }
)


def _virtfs_stage_copytree_ignore(_src: str, names: list[str]) -> list[str]:
    """Names to skip when staging exec trees into tmpfs (nested container / K8s).

    A full ``copytree`` of a dev checkout (many ``.venv``, IDE dirs, ``samples``)
    often hits **ENOMEM** or **OSError** 526 on virtio-9p / overlay mounts.
    """
    ignored: list[str] = []
    for name in names:
        if name in _VIRTFS_STAGE_SKIP_DIR_NAMES:
            ignored.append(name)
        elif name.endswith(".egg-info"):
            ignored.append(name)
    return ignored


def _stage_exec_virtfs_mounts(
    temp: Path,
    mount_specs: list[tuple[str, Path, str]],
) -> None:
    """Copy pysb_exec_* host trees under temp/virtfs_stage_exec/... and point virtfs there.

    Keeps guest_path unchanged so RPATH and imports still match. Source must be a
    directory tree (as produced by _execution_dirs_mounts).
    """
    stage_root = (temp / "virtfs_stage_exec").resolve()
    stage_root.mkdir(parents=True, exist_ok=True)
    did_any = False
    for i, (tag, host_path, guest_path) in enumerate(mount_specs):
        if not tag.startswith("pysb_exec_"):
            continue
        gp = Path(guest_path)
        if not gp.is_absolute():
            continue
        rel = Path(*gp.parts[1:])  # usr/local/bin under stage_root
        dest = (stage_root / rel).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if host_path.is_dir():
                shutil.copytree(
                    host_path,
                    dest,
                    symlinks=True,
                    dirs_exist_ok=True,
                    ignore=_virtfs_stage_copytree_ignore,
                )
            elif host_path.is_file():
                shutil.copy2(host_path, dest)
            else:
                logger.warning("virtfs staging: skip missing path %s (tag %s)", host_path, tag)
                continue
        except OSError as e:
            logger.error("virtfs staging: copy %s -> %s failed: %s", host_path, dest, e)
            raise
        mount_specs[i] = (tag, dest, guest_path)
        did_any = True
        logger.debug("virtfs staging: %s -> %s (guest %s)", host_path, dest, guest_path)
    if did_any:
        logger.debug(
            "QEMU virtio-9p: staged exec mounts under %s (container/overlay workaround)",
            stage_root,
        )


def _merge_staged_virtfs_into_expose_mounts(
    mount_specs: list[tuple[str, Path, str]],
) -> None:
    """Point file-rule 9p mounts at staged trees and drop redundant pysb_exec_* mounts.

    After staging, ``pysb_exec_*`` and ``pysb_<n>`` can refer to the same guest path
    (e.g. ``/app`` vs ``/app/``); the expose mount must use the staged host path and the
    duplicate exec virtfs entry must be removed so the guest does not mount overlay twice.
    """
    staged_by_guest: dict[str, Path] = {}
    for tag, host_path, guest_path in mount_specs:
        if tag.startswith("pysb_exec_"):
            staged_by_guest[_norm_guest_path(guest_path)] = host_path
    if not staged_by_guest:
        return
    for i, (tag, _host_path, guest_path) in enumerate(mount_specs):
        if not tag.startswith("pysb_") or not tag[5:].isdigit():
            continue
        key = _norm_guest_path(guest_path)
        if key in staged_by_guest:
            mount_specs[i] = (tag, staged_by_guest[key], guest_path)
    file_norm_guests = {
        _norm_guest_path(guest_path)
        for tag, _h, guest_path in mount_specs
        if tag.startswith("pysb_") and tag[5:].isdigit()
    }
    mount_specs[:] = [
        m for m in mount_specs if not (m[0].startswith("pysb_exec_") and _norm_guest_path(m[2]) in file_norm_guests)
    ]


def _rebase_file_expose_hosts_under_staged_app(
    mount_specs: list[tuple[str, Path, str]],
) -> None:
    """Point expose-ro children of /app (e.g. ./tmp -> /app/tmp) at the staged /app tree.

    Otherwise a second -virtfs for /app/tmp still uses the container overlay and breaks
    mmap in the guest for paths under /app.
    """
    staged_app: Path | None = None
    for tag, hp, gp in mount_specs:
        if tag.startswith("pysb_") and tag[5:].isdigit() and _norm_guest_path(gp) == "/app":
            staged_app = hp
            break
    if staged_app is None:
        return
    app_root = Path("/app").resolve()
    for i, (tag, host_path, guest_path) in enumerate(mount_specs):
        if not tag.startswith("pysb_") or not tag[5:].isdigit():
            continue
        hr = host_path.resolve()
        if _norm_guest_path(guest_path) == "/app":
            continue
        try:
            rel = hr.relative_to(app_root)
        except ValueError:
            continue
        new_host = (staged_app / rel).resolve()
        mount_specs[i] = (tag, new_host, guest_path)
        logger.debug(
            "virtfs staging: rebase expose mount %s -> %s (guest %s)",
            hr,
            new_host,
            guest_path,
        )


_LDD_ARROW = re.compile(r"^\s*\S+\s*=>\s+(\S+)\s")
_LDD_STATIC = re.compile(r"^\s+(/lib64/ld-linux-x86-64\.so\.2)\s")


def _ldd_resolved_paths(elf: Path) -> set[Path]:
    """Return resolved paths from ``ldd`` for a shared library or PIE executable."""
    try:
        r = subprocess.run(
            ["ldd", str(elf)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if r.returncode != 0:
        return set()
    out: set[Path] = set()
    for line in r.stdout.splitlines():
        m = _LDD_ARROW.match(line)
        if m:
            p = Path(m.group(1))
            if p.is_file():
                try:
                    out.add(p.resolve(strict=True))
                except OSError:
                    pass
            continue
        m2 = _LDD_STATIC.match(line)
        if m2:
            p = Path(m2.group(1))
            if p.is_file():
                try:
                    out.add(p.resolve(strict=True))
                except OSError:
                    pass
    return out


_ELF_MAGIC = b"\x7fELF"


def _debian_multiarch_triplet(machine: str | None = None) -> str | None:
    """Map ``platform.machine()`` to Debian ``/lib/<triplet>`` (e.g. ``x86_64-linux-gnu``)."""
    m = (machine or platform.machine() or "").strip().lower()
    table = {
        "x86_64": "x86_64-linux-gnu",
        "x86-64": "x86_64-linux-gnu",
        "amd64": "x86_64-linux-gnu",
        "aarch64": "aarch64-linux-gnu",
        "arm64": "aarch64-linux-gnu",
        "armv8l": "aarch64-linux-gnu",
        "armv7l": "arm-linux-gnueabihf",
    }
    return table.get(m)


def _normalize_ld_closure_libs_param(raw: str | None) -> str:
    """Return ``full`` or ``sparse`` (default ``full`` for nested lib overlay safety)."""
    v = (raw or "full").strip().lower()
    if v in ("sparse", "minimal", "ldd"):
        return "sparse"
    if v in ("full", "wide", "multiarch", "yes", "true", "1"):
        return "full"
    logger.warning("Unknown qemu.ld_closure_libs value %r; using full", raw)
    return "full"


def _path_under_host_multiarch_lib(p: Path, triplet: str) -> bool:
    """True if ``p`` lies under ``/lib/<triplet>`` or ``/usr/lib/<triplet>`` by path prefix.

    Uses :func:`os.path.normpath` only (no symlink resolution): ``/lib64/ld-linux-…``
    can resolve into the triplet tree on disk, but staging still copies it under
    ``ld_closure_fs/lib64``; skipping it would drop the loader from the sparse loop.
    """
    ap = Path(os.path.normpath(p))
    for base in (Path(f"/lib/{triplet}"), Path(f"/usr/lib/{triplet}")):
        try:
            ap.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def _merge_full_multiarch_lib_dirs(ld_root: Path, triplet: str) -> None:
    """Copy entire host ``/lib/<triplet>`` and ``/usr/lib/<triplet>`` into staged tree.

    Safer than an ``ldd``-only file list + .so whitelist: any DSO shipped under those
    dirs on the container image (zlib, NSS, ICU, etc.) is available to the guest Python.

    In ``full`` mode this must run **before** per-path ``ldd`` copies: those use
    ``copy2(..., follow_symlinks=True)``, which materializes real files where the host
    has SONAME symlinks; a later ``copytree`` then hits EEXIST trying to recreate links.
    """
    pairs = [
        (Path(f"/lib/{triplet}"), ld_root / "lib" / triplet),
        (Path(f"/usr/lib/{triplet}"), ld_root / "usr" / "lib" / triplet),
    ]
    for src, dst in pairs:
        if not src.is_dir():
            logger.debug("ld closure: full merge skip missing %s", src)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
        except OSError as e:
            logger.warning("ld closure: full merge %s -> %s failed: %s", src, dst, e)
    logger.debug(
        "QEMU virtio-9p: merged full host multiarch lib dirs for %s under %s",
        triplet,
        ld_root,
    )


def _qemu_bootstrap_ldd_seed_executables() -> list[Path]:
    """ELF paths merged into the staged /lib* closure when nested virtio-9p is used.

    Staging mounts host ``/lib/x86_64-linux-gnu`` (and friends) over the guest tree so
    the container Python matches its libc.  That replaces the guest Ubuntu libs with a
    **subset** built from Python's ``ldd`` closure only.  The cloud-init bootstrap then
    runs host-linked ``mkdir``, ``mount``, ``sh``, etc.; they need extra deps (e.g.
    ``libselinux.so.1``, ``libsystemd.so.0``) that Python does not pull in — without
    them, ``mkdir`` fails and the guest appears to hang while the host waits on QEMU.
    """
    names = (
        "mkdir",
        "mount",
        "umount",
        "sh",
        "bash",
        "dash",
        "sed",
        "grep",
        "readlink",
        "chmod",
        "dirname",
        "basename",
        "true",
        "poweroff",
        "logger",
        "ssh-keygen",
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for name in names:
        w = shutil.which(name)
        if not w:
            continue
        try:
            p = Path(w).resolve(strict=True)
        except OSError:
            continue
        if not p.is_file() or p in seen:
            continue
        try:
            with p.open("rb") as f:
                if f.read(4) != _ELF_MAGIC:
                    continue
        except OSError:
            continue
        seen.add(p)
        out.append(p)
    return out


def _qemu_guest_overlay_compat_so_seeds() -> list[Path]:
    """DSOs an Ubuntu cloud guest's /bin/mkdir and /bin/mount need after /lib is overlaid.

    Seeds from :func:`_qemu_bootstrap_ldd_seed_executables` use the **host** (container)
    ``mkdir``.  On Debian-slim that binary often **does not** link ``libselinux``; the
    **guest** ``mkdir`` still does, so after 9p replaces ``/lib/x86_64-linux-gnu`` the
    guest ELF loads our staged tree and fails on missing ``libselinux`` or
    ``libpcre2-8`` (dependency of libselinux).  Seeding these .so paths pulls their
    ``ldd`` transitive closure into the staged copy.
    """
    basenames = (
        "libselinux.so.1",
        "libpcre2-8.so.0",
        "libmount.so.1",
        "libblkid.so.1",
        "libuuid.so.1",
        "libsmartcols.so.1",
        "libsystemd.so.0",
        "liblzma.so.5",
        "libgcrypt.so.20",
        # stdlib ``binascii`` / ``zlib`` C extension loads libz; not always in interpreter ldd
        "libz.so.1",
    )
    triplet = _debian_multiarch_triplet() or "x86_64-linux-gnu"
    dirs = (Path(f"/lib/{triplet}"), Path(f"/usr/lib/{triplet}"))
    seen: set[Path] = set()
    out: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for base in basenames:
            p = d / base
            if not p.is_file():
                continue
            try:
                r = p.resolve(strict=True)
            except OSError:
                continue
            if r in seen:
                continue
            seen.add(r)
            out.append(r)
        # poweroff/systemctl pull a versioned libsystemd-shared-NNN.so not always named by ldd seeds
        try:
            for p in sorted(d.glob("libsystemd-shared*.so*")):
                if not p.is_file():
                    continue
                try:
                    r = p.resolve(strict=True)
                except OSError:
                    continue
                if r not in seen:
                    seen.add(r)
                    out.append(r)
        except OSError:
            pass
    return out


def _dynamic_linker_closure_paths() -> set[Path]:
    """Paths so guest uses the host (container) dynamic linker + libc for sys.executable."""
    exe_launcher = Path(sys.executable)
    bin_paths: set[Path] = set()
    follow_links_executable(exe_launcher, bin_paths)
    _bin_paths_include_resolved_interpreter(exe_launcher, bin_paths)
    exe: Path | None = None
    for p in bin_paths:
        if p.is_file():
            exe = p.resolve(strict=True)
            break
    if exe is None:
        try:
            exe = exe_launcher.resolve(strict=True)
        except OSError:
            return set()
    interp = Path("/lib64/ld-linux-x86-64.so.2")
    if not interp.is_file():
        alt = Path("/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2")
        interp = alt if alt.is_file() else interp
    seeds: set[Path] = {exe}
    if interp.is_file():
        try:
            seeds.add(interp.resolve(strict=True))
        except OSError:
            pass
    bootstrap_utils = _qemu_bootstrap_ldd_seed_executables()
    for util in bootstrap_utils:
        seeds.add(util)
    if bootstrap_utils:
        logger.debug(
            "QEMU ld closure: added bootstrap utility seeds for nested /lib overlay: %s",
            [str(p) for p in bootstrap_utils],
        )
    overlay_so = _qemu_guest_overlay_compat_so_seeds()
    for so in overlay_so:
        seeds.add(so)
    if overlay_so:
        logger.debug(
            "QEMU ld closure: added guest-compat .so seeds for nested /lib overlay: %s",
            [p.name for p in overlay_so],
        )
    closure: set[Path] = set()
    stack = list(seeds)
    while stack:
        p = stack.pop()
        if p in closure or not p.is_file():
            continue
        closure.add(p)
        for dep in _ldd_resolved_paths(p):
            if dep not in closure:
                stack.append(dep)
    return closure


def _ensure_ld_closure_soname_symlink(dest: Path) -> None:
    """Create ``libfoo.so.N`` -> ``libfoo.so.N.x.y`` if the linker expects the SONAME.

    ``ldd`` resolves to the versioned file (e.g. ``libpcre2-8.so.0.14.0``); the dynamic
    loader still opens ``libpcre2-8.so.0``.  Copying only the realpath leaves that name
    missing on virtio-9p and bootstrap ``mkdir`` fails.
    """
    name = dest.name
    if ".so." not in name:
        return
    prefix, rest = name.split(".so.", 1)
    abi = rest.split(".")[0]
    if not abi.isdigit():
        return
    soname = f"{prefix}.so.{abi}"
    if soname == name:
        return
    link = dest.parent / soname
    if link.exists() or link.is_symlink():
        return
    try:
        link.symlink_to(name)
    except OSError as e:
        logger.debug("ld closure: could not soname-symlink %s -> %s: %s", soname, name, e)


def _stage_dynamic_linker_closure(temp: Path, *, ld_closure_libs: str = "full") -> list[tuple[str, Path, str]]:
    """Copy ldd closure of the host interpreter; mount loader + glibc paths on the guest.

    PT_INTERP must resolve to the host loader on 9p, not the guest disk, or libc
    mismatches the Python ELF from the container (SIGSEGV in the guest).

    ``ld_closure_libs`` (profile ``qemu.ld_closure_libs``): ``full`` (default) copies
    host ``/lib/<triplet>`` and ``/usr/lib/<triplet>`` first, then copies any remaining
    ``ldd`` paths (outside those trees) so extension modules rarely miss a DSO without
    EEXIST from mixing followed copies and host symlinks; ``sparse`` keeps only the
    transitive ``ldd`` closure plus :func:`_qemu_guest_overlay_compat_so_seeds` (faster, smaller).
    """
    closure = _dynamic_linker_closure_paths()
    if not closure:
        return []
    triplet = _debian_multiarch_triplet() or "x86_64-linux-gnu"
    root = (temp / "ld_closure_fs").resolve()
    root.mkdir(parents=True, exist_ok=True)
    if ld_closure_libs == "full":
        _merge_full_multiarch_lib_dirs(root, triplet)
    for p in sorted(closure, key=lambda x: str(x)):
        if ld_closure_libs == "full" and _path_under_host_multiarch_lib(p, triplet):
            continue
        try:
            rel = p.relative_to("/")
        except ValueError:
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(p, dest, follow_symlinks=True)
            _ensure_ld_closure_soname_symlink(dest)
        except OSError as e:
            logger.warning("ld closure: skip %s: %s", p, e)
    # PT_INTERP is /lib64/ld-linux-x86-64.so.2; on Debian bookworm it may live under usr/lib only.
    interp_guest = Path("/lib64/ld-linux-x86-64.so.2")
    if interp_guest.is_file():
        ld64 = root / "lib64"
        ld64.mkdir(parents=True, exist_ok=True)
        try:
            ld_dest = ld64 / "ld-linux-x86-64.so.2"
            shutil.copy2(interp_guest, ld_dest, follow_symlinks=True)
            _ensure_ld_closure_soname_symlink(ld_dest)
        except OSError as e:
            logger.warning("ld closure: could not stage PT_INTERP: %s", e)
    ulx = root / "usr" / "lib" / triplet
    libgnu = root / "lib" / triplet
    guest_usr = f"/usr/lib/{triplet}"
    guest_lib = f"/lib/{triplet}"
    out: list[tuple[str, Path, str]] = []
    if (root / "lib64").is_dir():
        out.append(("pysb_lib64", root / "lib64", "/lib64"))
    # Guest ld.so searches /lib/<triplet> before /usr/lib/...; ldd closure often
    # lands only under usr/lib. Mounting a sparse lib/ tree breaks the Python probe and
    # coreutils. Prefer one full tree at both guest paths (same host dir, two 9p tags).
    if ulx.is_dir():
        out.append(("pysb_usr_lib_gnu", ulx, guest_usr))
        out.append(("pysb_lib_gnu", ulx, guest_lib))
    elif libgnu.is_dir():
        out.append(("pysb_lib_gnu", libgnu, guest_lib))
    if out:
        mode = "full multiarch merge + ldd seeds" if ld_closure_libs == "full" else "sparse ldd + compat seeds"
        logger.debug(
            "QEMU virtio-9p: staged dynamic linker closure (%d ldd objects, %s) for "
            "container interpreter + shell/bootstrap utils (nested /lib overlay)",
            len(closure),
            mode,
        )
    return out


def _stage_overlay_etc_expose_mount(
    temp: Path,
    mount_specs: list[tuple[str, Path, str]],
) -> None:
    """Copy expose-ro /etc from container overlay into temp so 9p mmap is safe in the guest."""
    misc = (temp / "virtfs_stage_misc").resolve()
    for i, (tag, host_path, guest_path) in enumerate(mount_specs):
        if not tag.startswith("pysb_") or not tag[5:].isdigit():
            continue
        if _norm_guest_path(guest_path) != "/etc":
            continue
        if not host_path.is_dir():
            continue
        dest = misc / "etc"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(host_path, dest, symlinks=True, dirs_exist_ok=True)
        except OSError as e:
            logger.error("virtfs staging: copy /etc expose mount failed: %s", e)
            raise
        mount_specs[i] = (tag, dest, guest_path)
        logger.debug("virtfs staging: /etc expose mount copied to %s", dest)
        return


def _add_peer_lib_dir_for_executables(dirs: set[Path], bin_paths: set[Path]) -> None:
    """Add ``<prefix>/lib`` when the interpreter lives in ``<prefix>/bin`` (Docker Python layout).

    Official images place ``libpythonX.Y.so.*`` under ``/usr/local/lib`` while ``sys.executable``
    is ``/usr/local/bin/pythonX.Y``; without a 9p mount of that ``lib``, the guest binary loads
    only ``../lib/pythonX.Y/...`` mounts and fails with ``libpython*.so: cannot open``.
    """
    for p in bin_paths:
        if not p.is_file():
            continue
        try:
            er = p.resolve(strict=True)
        except OSError:
            continue
        peer = er.parent.parent / "lib"
        if not peer.is_dir():
            continue
        try:
            pr = peer.resolve(strict=True)
        except OSError:
            continue
        if any(pr.glob("libpython*.so*")):
            dirs.add(pr)


def _add_libpython_dirs_from_ldd(dirs: set[Path], bin_paths: set[Path]) -> None:
    """Add directories containing ``libpython*.so*`` reported by ``ldd`` on the real interpreter.

    Peer ``../lib`` misses layouts where ``bin`` is not ``<prefix>/bin`` (symlinks, distros).
    """
    for p in bin_paths:
        if not p.is_file():
            continue
        try:
            er = p.resolve(strict=True)
        except OSError:
            continue
        for dep in _ldd_resolved_paths(er):
            if "libpython" not in dep.name:
                continue
            try:
                dirs.add(dep.parent.resolve(strict=True))
            except OSError:
                pass


def _execution_dirs_mounts() -> list[tuple[str, Path, str]]:
    """Build 9p mounts for Python execution: sys.executable (follow symlinks), sys.path, site.getsitepackages().

    Same strategy as sse_firejail: follow links so venv/conda symlinks work. Guest path = host path
    so the guest Python finds the same libraries.
    """
    dirs: set[Path] = set()
    # sys.executable and its symlink chain (e.g. .venv/bin/python3 -> python -> /opt/conda/bin/python3.13)
    bin_paths: set[Path] = set()
    exe_launcher = Path(sys.executable)
    follow_links_executable(exe_launcher, bin_paths)
    _bin_paths_include_resolved_interpreter(exe_launcher, bin_paths)
    for p in bin_paths:
        if p.is_file():
            dirs.add(p.parent.resolve(strict=True))
        else:
            _add_dir_follow_links(p, dirs)
    _add_peer_lib_dir_for_executables(dirs, bin_paths)
    _add_libpython_dirs_from_ldd(dirs, bin_paths)
    # sys.path and site.getsitepackages()
    for sp in sys.path:
        if sp and os.path.isdir(sp):
            _add_dir_follow_links(Path(sp), dirs)
    for sp in site.getsitepackages():
        if sp and os.path.isdir(sp):
            _add_dir_follow_links(Path(sp), dirs)
    # Deduplicate and build (tag, host_path, guest_path) with guest_path = host_path
    seen: set[Path] = set()
    mount_specs: list[tuple[str, Path, str]] = []
    for i, d in enumerate(sorted(dirs, key=lambda p: str(p))):
        d_res = d.resolve(strict=True)
        if not d_res.is_dir() or d_res in seen:
            continue
        seen.add(d_res)
        tag = f"pysb_exec_{i}"
        guest_path = str(d_res)
        mount_specs.append((tag, d_res, guest_path))
    return mount_specs


def _file_rules_mounts(
    all_rules: AllRules,
    temp: Path,
    pipe_path: Path,
    config_dir: Path | None = None,
) -> tuple[list[tuple[str, Path, str]], list[tuple[str, str]]]:
    """Build one 9p (tag, host_path, guest_path) per FSExposeRule, run dir, optional config dir, and execution dirs.

    Returns (mount_specs, mount_list_for_iso) where mount_specs is used for -virtfs
    and mount_list_for_iso is [(tag, guest_path), ...] for the bootstrap script.
    When config_dir is set, it is mounted at GUEST_CONFIG_MOUNT so the guest reads config from a regular file via 9p.
    """
    mount_specs: list[tuple[str, Path, str]] = []
    mount_list: list[tuple[str, str]] = []
    for i, rule in enumerate(all_rules.file_rules):
        if not isinstance(rule, FSExposeRule):
            continue
        host_path = Path(rule.path.rstrip("/")).resolve()
        if host_path.is_file():
            host_path = host_path.parent
        if not host_path.exists():
            continue
        tag = f"pysb_{i}"
        guest_path = str(host_path)
        mount_specs.append((tag, host_path, guest_path))
        mount_list.append((tag, guest_path))
    # Run dir (temp) for exitcode etc.
    if temp.is_dir():
        tag_run = "pysb_run"
        mount_specs.append((tag_run, temp, GUEST_RUN_MOUNT))
        mount_list.append((tag_run, GUEST_RUN_MOUNT))
    # Config dir: dedicated 9p mount so guest sees config.pkl as a regular file (avoids FIFO/9p issues)
    if config_dir is not None and config_dir.is_dir():
        tag_config = "pysb_config"
        mount_specs.append((tag_config, config_dir, GUEST_CONFIG_MOUNT))
        mount_list.append((tag_config, GUEST_CONFIG_MOUNT))
    # Execution dirs: sys.executable, getsitepackages(), sys.path (follow symlinks)
    stage_exec = _virtfs_stage_exec_needed(all_rules.os_sandbox_params)
    existing_guest_paths = {_norm_guest_path(gp) for (_, gp) in mount_list}
    for tag, host_path, guest_path in _execution_dirs_mounts():
        gkey = _norm_guest_path(guest_path)
        # When staging for container/overlay, we still add exec dirs that duplicate an expose
        # (e.g. /app vs expose-ro .) so /app is copied to tmpfs; merge step then drops the
        # redundant pysb_exec_* and retargets the expose mount at the staged tree.
        if gkey in existing_guest_paths and not stage_exec:
            continue
        existing_guest_paths.add(gkey)
        mount_specs.append((tag, host_path, guest_path))
        mount_list.append((tag, guest_path))

    if stage_exec:
        _stage_exec_virtfs_mounts(temp, mount_specs)
        _merge_staged_virtfs_into_expose_mounts(mount_specs)
        _rebase_file_expose_hosts_under_staged_app(mount_specs)
        _stage_overlay_etc_expose_mount(temp, mount_specs)
        # Prepend so sort places these before project expose mounts; guest must see host ld.so/libc.
        ld_mode = _normalize_ld_closure_libs_param(str(all_rules.os_sandbox_params.get("ld_closure_libs", "full")))
        mount_specs[:] = _stage_dynamic_linker_closure(temp, ld_closure_libs=ld_mode) + mount_specs

    mount_list = [(tag, gp) for tag, _hp, gp in mount_specs]

    # Keep deterministic mount order while preserving semantics:
    # - File rules first (pysb_<idx>) so project paths can override import resolution.
    # - Within file rules, parent paths first, so writable child mounts (e.g. .../tmp)
    #   can override read-only parent mounts.
    # - Runtime/config mounts next, execution dirs last.
    def _mount_order(tag: str, guest_path: str) -> tuple[int, int, int, str]:
        if tag in ("pysb_lib64", "pysb_lib", "pysb_usr_lib_gnu", "pysb_lib_gnu"):
            return (-1, 0, 0, guest_path)
        if tag.startswith("pysb_") and tag[5:].isdigit():
            depth = len(Path(guest_path).parts)
            return (0, depth, int(tag[5:]), guest_path)
        if tag == "pysb_config":
            return (1, 0, 0, guest_path)
        if tag == "pysb_run":
            return (1, 1, 0, guest_path)
        if tag.startswith("pysb_exec_") and tag[9:].isdigit():
            return (2, 0, int(tag[9:]), guest_path)
        return (3, 0, 0, guest_path)

    mount_list.sort(key=lambda m: _mount_order(m[0], m[1]))
    mount_specs.sort(key=lambda m: _mount_order(m[0], m[2]))
    return mount_specs, mount_list


def _qemu_binary() -> str:
    """Return the QEMU system binary for the current architecture."""
    arch = platform.machine()
    name = f"qemu-system-{arch}"
    path = which_command(name)
    if path is not None:
        return str(path)
    if arch != "x86_64":
        path = which_command("qemu-system-x86_64")
        if path is not None:
            return str(path)
    return name  # Let subprocess fail with a clear error if not in PATH


class QemuSSEDaemon(VMSSEDaemon):
    """SSE daemon that runs the sandbox inside a QEMU VM.

    Config is embedded in the NoCloud ISO; pysandboxes source is shared via
    virtio-9p so no file copies or HTTP server are needed.
    """

    host_run_temp_prefix = QEMU_HOST_RUN_PREFIX

    __slots__ = ("_iso_config", "_qemu_console_tasks")

    def guest_run_dir_mount(self) -> str:
        return GUEST_RUN_MOUNT

    def augment_rules_for_guest_run_mount(self, all_rules: AllRules) -> AllRules:
        return augment_all_rules_for_qemu_run_mount(all_rules)

    def __init__(self, token: str, *, python_args: list[str] | None = None, **kwargs: Any) -> None:
        # Force IPv4 so hostfwd (TCP only on 0.0.0.0) is used; "localhost" can resolve to ::1.
        super().__init__(
            token,
            python_args=python_args or [],
            host="127.0.0.1",
            **kwargs,
        )
        self._iso_config: DaemonParameters | None = None
        self._qemu_console_tasks: list[asyncio.Task[None]] = []

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        """Parse qemu.* lines into os_sandbox_params; pass rest through."""
        params: dict[str, str] = {}
        rest: ConfigLines = []
        for rule in rules:
            if rule.rule.startswith("qemu."):
                part = rule.rule[len("qemu.") :].strip()
                if "=" in part:
                    key, _, val = part.partition("=")
                    params[key.strip()] = val.strip()
                else:
                    params[part.strip()] = ""
            else:
                rest.append(rule)
        return ImmutableDict(params), rest

    def _build_qemu_cmd(
        self,
        all_rules: AllRules,
        temp: Path,
        process_config: "DaemonParameters",
        port: int,
        pipe_path: Path,
        config_dir: Path | None = None,
    ) -> tuple[Args, Environ]:
        """Build QEMU command: one virtio-9p tag per file_rule FSExposeRule + run dir.

        Optional config dir; ISO with 9p_mounts + pipe_name.
        """
        image_path = get_default_image_path()
        ensure_image(image_path)
        mount_specs, mount_list = _file_rules_mounts(all_rules, temp, pipe_path, config_dir=config_dir)
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        config_guest_path = f"{GUEST_CONFIG_MOUNT}/config.pkl" if config_dir else None
        nocloud_iso = prepare_guest_env(
            temp,
            process_config,
            pipe_path=pipe_path,
            mounts=mount_list,
            pipe_run_guest_path=GUEST_RUN_MOUNT,
            python_version=python_version,
            python_exe=_guest_python_exe_path(),
            config_guest_path=config_guest_path,
        )

        # Keys match parse_rules: "qemu.foo=bar" → os_sandbox_params["foo"] (no "qemu." prefix)
        use_kvm = all_rules.os_sandbox_params.get("use_kvm", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        enable_kvm = ["-enable-kvm"] if use_kvm and is_kvm_available() else []

        # Default 2 GiB: Ubuntu cloud images + Python need ~2G to avoid OOM (see Ubuntu QEMU docs)
        raw_memory = all_rules.os_sandbox_params.get("memory", "2048").strip()
        memory = normalize_qemu_m_memory_arg(raw_memory)

        net = [
            "-nic",
            f"user,hostfwd=tcp::{port}-:{port},model=virtio-net-pci",
        ]

        virtfs_args: Args = []
        for tag, host_path, guest_path in mount_specs:
            # mapped-xattr: guest sees normal files (e.g. config). Staged trees (tmpfs copies)
            # from container overlay: use "none" so ELF/DSO mmap is reliable in the guest.
            host_s = str(host_path.resolve())
            if (
                "virtfs_stage_exec" in host_s
                or "virtfs_stage_misc" in host_s
                or "/virtfs_stage/" in host_s
                or "ld_closure_fs" in host_s
            ):
                # Staged/copied trees: "none" avoids 9p symlink issues (ELOOP loading .so)
                # with mapped-xattr; see nested QEMU ld_closure + SONAME symlinks.
                security = "none"
            else:
                configured = (
                    str(all_rules.os_sandbox_params.get("virtfs_security_model", "mapped-xattr")).strip().lower()
                )
                # QEMU has no security_model=auto; treat as mapped-xattr (guest-friendly default).
                security = "mapped-xattr" if configured in ("auto", "") else configured
            virtfs_args.extend(
                [
                    "-virtfs",
                    f"local,path={host_path!s},id={tag},security_model={security},mount_tag={tag}",
                ]
            )
            logger.debug("qemu 9p: %s -> %s", tag, guest_path)

        qga = [
            "-device",
            "virtio-serial-pci",
            "-device",
            "virtserialport,name=org.qemu.guest_agent.0",
        ]

        # Ubuntu cloud images use .img extension but are QCOW2 format (see Ubuntu docs)
        use_qcow2 = image_path.suffix == ".qcow2" or (image_path.suffix == ".img" and "cloudimg" in image_path.name)
        drive_image = (
            f"file={image_path!s},format=qcow2,if=virtio" if use_qcow2 else f"file={image_path!s},format=raw,if=virtio"
        )
        drive_nocloud = f"file={nocloud_iso!s},format=raw,if=virtio"
        cmd: Args = [
            _qemu_binary(),
            *enable_kvm,
            "-m",
            memory,
            "-snapshot",
            "-drive",
            drive_image,
            "-drive",
            drive_nocloud,
            "-nographic",
            *net,
            *virtfs_args,
            *qga,
        ]
        return cmd, {}

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build QEMU command for python_sb path (config pre-set via _iso_config).

        For the daemon path (_re_start_cmd), this returns an empty command since
        _re_start_cmd builds everything itself. For the python_sb path, process_config
        is set as _iso_config before this call so the ISO can be built with it embedded.
        """
        process_config = getattr(self, "_iso_config", None)
        if process_config is None:
            # Daemon path: _re_start_cmd handles ISO creation and launch
            return [], {}
        # python_sb path: config in 9p dir; use ./tmp/ when DEBUG_CONFIG for inspection
        if DEBUG_CONFIG:
            config_dir = Path("tmp") / "pysb_config"
        else:
            config_dir = temp / "pysb_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        # serialization only
        (config_dir / "config.pkl").write_bytes(pickle.dumps(process_config))
        return self._build_qemu_cmd(
            all_rules,
            temp,
            process_config,
            self.port,
            pipe_path,
            config_dir=config_dir,
        )

    @override
    async def _re_start_cmd(
        self,
        all_rules: AllRules,
        args: Args,
        extra_envs: Environ,
        pipe_path: Path,
        port: int,
        *,
        log_level: int,
        init_fn: Any,
    ) -> None:
        """Build NoCloud ISO (bootstrap + pipe_name), then launch QEMU.

        Guest mounts /app (file_rules root) and /mnt/pysandbox_run (temp with FIFO)
        via 9p, runs main_sandbox --_named-pipe; host writes config to the pipe
        when the guest opens it (same flow as bwrap/unshare).
        """
        from .client_subprocess_sse_daemon import get_callable_info

        self._is_started = False
        self._accept_incoming = False
        init_fn_ref = ""
        if init_fn:
            module, func_ref = get_callable_info(init_fn)
            init_fn_ref = f"{module}:{func_ref}"

        dns_guest = [IPv4Address("10.0.2.3")]
        netfilter_list = list(rule_to_netfilter(all_rules.socket_rules, dns_guest, is_ipv6=False))
        # Allow host (10.0.2.2 in QEMU user mode) to reach the SSE server port.
        if "COMMIT" in netfilter_list:
            idx = netfilter_list.index("COMMIT")
            sse_allow = (
                f"-A INPUT -p tcp -s 10.0.2.2/32 --dport {port} " "-m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT"
            )
            netfilter_list = netfilter_list[:idx] + [sse_allow] + netfilter_list[idx:]
        netfilter_rules: tuple[str, ...] = tuple(netfilter_list)

        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            use_rich_handler=use_rich_handler(),
            token=self._token,
            port=port,
            init_fn=init_fn_ref,
            netfilter_rules=netfilter_rules,
            guest_run_dir=GUEST_RUN_MOUNT,
            guest_working_dir=str(Path.cwd().resolve()),
        )

        env: dict[str, str]
        if all_rules.learn:
            env = {**dict(os.environ), **dict(all_rules.envs)}
        else:
            env = dict(all_rules.envs)
        env = {**env, **extra_envs}

        temp = pipe_path.parent
        # Avoid race on param files: DEBUG_CONFIG → file under ./tmp/ for inspection; else named pipe.
        if DEBUG_CONFIG:
            config_dir = Path("tmp") / "pysb_config"
            config_dir.mkdir(parents=True, exist_ok=True)
            # serialization only
            (config_dir / "config.pkl").write_bytes(pickle.dumps(process_config))
        else:
            config_dir = None

        cmd, _ = self._build_qemu_cmd(all_rules, temp, process_config, port, pipe_path, config_dir=config_dir)

        logger.debug("Launch QEMU: %s", " ".join((repr(a) if " " in a else a for a in cmd)))

        # When DEBUG_CONFIG, config is in 9p-mounted dir; else launch_sandbox writes to FIFO
        def _noop_config_writer(_: DaemonParameters) -> None:
            pass

        config_writer = _noop_config_writer if config_dir is not None else None
        show_boot = self.show_boot_console_truthy(all_rules)
        # When show_boot_console is false (default), redirect QEMU stdout/stderr so
        # boot/kernel/cloud-init traces are hidden; Python output is streamed via SSE.
        launch_kwargs: dict[str, Any] = dict(
            cmd=cmd,
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
            config_writer=config_writer,
            # -nographic multiplexes serial on stdio; inheriting a TTY (e.g. podman -it)
            # can block forever waiting for console input while the guest is unattended.
            stdin=subprocess.DEVNULL,
        )
        if not show_boot:
            launch_kwargs["stdout"] = subprocess.DEVNULL
            launch_kwargs["stderr"] = subprocess.DEVNULL
        else:
            launch_kwargs["stdout"] = subprocess.PIPE
            launch_kwargs["stderr"] = subprocess.PIPE
        self._qemu_console_tasks = []
        self._process = await launch_sandbox(**launch_kwargs)
        if show_boot and self._process.stdout is not None:
            self._qemu_console_tasks = start_qemu_serial_drain_tasks(
                self._process,
                forward_all=True,
                mirror_logger=logger,
            )

        await self._on_process_started()

        gc.collect()
        ping_url = self.base_url.replace("{PORT}", str(port)) + "/ping"
        logger.debug(
            "Waiting %.0fs for QEMU guest to boot, then pinging %s (max %d attempts)",
            QEMU_BOOT_DELAY,
            ping_url,
            QEMU_LOOP_FOR_PING,
        )
        await asyncio.sleep(QEMU_BOOT_DELAY)
        import socket

        import aiohttp
        from aiohttp import ClientConnectorError, ClientOSError, ClientTimeout, ServerDisconnectedError

        # Force IPv4 so QEMU hostfwd is used (hostfwd is TCP on 0.0.0.0, not IPv6).
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            count_loop = 0
            while True:
                try:
                    count_loop += 1
                    if count_loop > QEMU_LOOP_FOR_PING:
                        logger.error(
                            "Cannot connect to sandbox daemon after %d attempts (%s)",
                            count_loop - 1,
                            ping_url,
                        )
                        raise SystemExit(-1)
                    async with session.get(
                        ping_url,
                        timeout=ClientTimeout(total=TIMEOUT_FOR_PING),
                    ) as response:
                        if response.status == 200:
                            logger.debug(
                                "Ping succeeded on attempt %d to %s",
                                count_loop,
                                ping_url,
                            )
                            break
                        logger.warning(
                            "Ping attempt %d: unexpected status %s from %s",
                            count_loop,
                            response.status,
                            ping_url,
                        )
                        raise RuntimeError(f"Unexpected status {response.status} from {ping_url}")
                except (
                    TimeoutError,
                    ClientConnectorError,
                    ServerDisconnectedError,
                ) as e:
                    if count_loop % 25 == 0 or count_loop <= 3:
                        logger.debug(
                            "Ping attempt %d/%d failed: %s",
                            count_loop,
                            QEMU_LOOP_FOR_PING,
                            type(e).__name__,
                        )
                except ClientOSError as e:
                    if not is_transient_connection_error(e):
                        raise
                    if count_loop % 25 == 0 or count_loop <= 3:
                        logger.debug(
                            "Ping attempt %d/%d failed: %s",
                            count_loop,
                            QEMU_LOOP_FOR_PING,
                            type(e).__name__,
                        )
                await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)

        await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        logger.debug(
            "QEMU sandbox daemon is up and running at %s (host will now accept RPCs)",
            ping_url,
        )
        self._is_started = True
        self._accept_incoming = True
