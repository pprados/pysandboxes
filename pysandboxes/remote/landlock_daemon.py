# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Landlock-based daemon for OS-level sandboxing.

This module implements a sandbox daemon that uses the Linux Landlock LSM
to restrict filesystem and network access of the sandbox process. It extends
BaseSubProcessDaemon and applies Landlock rules derived from file_rules and
socket_rules (TCP bind/connect only; ABI v4, kernel 6.7+).

Access modes:
- Read-only (ro): execute, read file, list directory.
- Read-write (rw): ro plus write file, remove file/dir, create (reg/dir/sym/char/sock/fifo/block),
  REFER (rename/link across dirs), TRUNCATE (creat, open(O_TRUNC), ftruncate).

Limitations of offering only write access (no read):
- Landlock does not support "write-only" as a useful mode: a directory must have READ_DIR
  to list and open entries, and READ_FILE to read. Our rw mode always includes ro, so
  writable paths behave like normal writable directories.
- chmod/chown are not restricted by Landlock; DAC still applies.
- On kernel ABI < 2, REFER is unavailable (rename/link only within same dir).
- On kernel ABI < 3, TRUNCATE is unavailable (open with O_TRUNC or creat may fail for
  existing files); we mask these flags so older kernels still work with reduced semantics.
"""

import ctypes
import logging
import os
import site
import sys
import tempfile
from ctypes import Structure, c_int, c_size_t, c_uint32
from pathlib import Path

from ..all_rules import AllRules
from ..guard_files import FSExposeRule
from ..guard_socket import Action, Direction, Kind, SocketRules
from ..override_compat import override
from ..sb_types import Envs
from .client_subprocess_sse_daemon import SubProcessDaemon

logger = logging.getLogger(__name__)

# Landlock ABI v1 (kernel 5.13+) filesystem access flags
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
# ABI v3 (kernel 6.2+): truncate with truncate(2), ftruncate(2), open(O_TRUNC), creat(2)
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

# Landlock ABI v4 (kernel 6.7+) network access flags
LANDLOCK_ACCESS_NET_BIND_TCP = 1 << 0
LANDLOCK_ACCESS_NET_CONNECT_TCP = 1 << 1
HANDLED_ACCESS_NET = LANDLOCK_ACCESS_NET_BIND_TCP | LANDLOCK_ACCESS_NET_CONNECT_TCP
LANDLOCK_RULE_NET_PORT = 2  # LANDLOCK_RULE_PATH_BENEATH = 1
LANDLOCK_CREATE_RULESET_VERSION = 1

# Handled access: all FS rights we may allow (ABI v1, REFER v2, TRUNCATE v3)
HANDLED_ACCESS_FS = (
    LANDLOCK_ACCESS_FS_EXECUTE
    | LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
    | LANDLOCK_ACCESS_FS_REFER
    | LANDLOCK_ACCESS_FS_TRUNCATE
)

# Read-only: execute, read files, list directory.
ACCESS_RO = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR
# Read-write: ACCESS_RO plus full directory semantics (create/remove/link/rename/truncate).
# Includes all MAKE_* so writable dirs can have subdirs, regular files, symlinks, sockets, FIFOs.
# REFER is required for rename/link across dirs. TRUNCATE is required for open(O_TRUNC)/creat/ftruncate.
ACCESS_RW = (
    ACCESS_RO
    | LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_SYM
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_REFER
    | LANDLOCK_ACCESS_FS_TRUNCATE
)

# Syscall numbers (Linux x86_64 and aarch64 common)
try:

    libc = ctypes.CDLL(None)
    syscall = libc.syscall
    syscall.restype = c_int
    # argtypes left unset for variadic (create_ruleset / add_rule / restrict_self)

    import platform

    machine = platform.machine()
    if machine == "x86_64" or machine == "amd64":
        _LANDLOCK_CREATE_RULESET = 444
        _LANDLOCK_ADD_RULE = 445
        _LANDLOCK_RESTRICT_SELF = 446
    elif machine == "aarch64" or machine == "arm64":
        _LANDLOCK_CREATE_RULESET = 444
        _LANDLOCK_ADD_RULE = 445
        _LANDLOCK_RESTRICT_SELF = 446
    else:
        _LANDLOCK_CREATE_RULESET = 444
        _LANDLOCK_ADD_RULE = 445
        _LANDLOCK_RESTRICT_SELF = 446

    class LandlockRulesetAttr(Structure):
        _fields_ = [
            ("handled_access_fs", ctypes.c_uint64),
            ("handled_access_net", ctypes.c_uint64),
            ("scoped", ctypes.c_uint64),
        ]

    class LandlockPathBeneathAttr(Structure):
        _fields_ = [
            ("allowed_access", ctypes.c_uint64),
            ("parent_fd", ctypes.c_int32),
        ]

    class LandlockNetPortAttr(Structure):
        _fields_ = [
            ("allowed_access", ctypes.c_uint64),
            ("port", ctypes.c_uint64),
        ]

    O_PATH = 0x2000  # Linux O_PATH
    PR_SET_NO_NEW_PRIVS = 38
    LANDLOCK_RULE_PATH_BENEATH = 1

except Exception:
    _LANDLOCK_CREATE_RULESET = -1
    _LANDLOCK_ADD_RULE = -1
    _LANDLOCK_RESTRICT_SELF = -1


def _landlock_available() -> bool:
    if _LANDLOCK_RESTRICT_SELF < 0:
        return False
    if sys.platform != "linux":
        return False
    # Quick probe: landlock_restrict_self with invalid fd returns EBADF, not ENOSYS
    try:
        err = syscall(_LANDLOCK_RESTRICT_SELF, -1, 0)
        if err == -1:
            errno = ctypes.get_errno()
            if errno == 38:  # ENOSYS
                return False
    except Exception:
        return False
    return True


def _get_landlock_abi_version() -> int:
    """Return Landlock ABI version (1+) or 0 if unsupported."""
    if _LANDLOCK_CREATE_RULESET < 0 or sys.platform != "linux":
        return 0
    try:
        abi = syscall(
            _LANDLOCK_CREATE_RULESET,
            None,
            c_size_t(0),
            c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
        )
        if abi < 0:
            return 0
        return abi
    except Exception:
        return 0


def _set_no_new_privs() -> None:
    libc.prctl.argtypes = [c_int, c_uint32, c_uint32, c_uint32, c_uint32]
    libc.prctl.restype = c_int
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_NO_NEW_PRIVS) failed")


def _collect_landlock_net_ports(
    socket_rules: SocketRules,
) -> list[tuple[int, bool, bool]]:
    """Build list of (port, allow_bind, allow_connect) for Landlock network rules.

    Only ALLOW rules for TCP are considered. Port 0 is valid (ephemeral bind).
    """
    port_access: dict[int, tuple[bool, bool]] = {}

    def merge(port: int, allow_bind: bool, allow_connect: bool) -> None:
        if port < 0 or port > 65535:
            return
        b, c = port_access.get(port, (False, False))
        port_access[port] = (b or allow_bind, c or allow_connect)

    for rule in socket_rules:
        if rule.action != Action.ALLOW:
            continue
        if Kind.TCP not in rule.mask.kinds:
            continue
        allow_bind = Direction.IN in rule.directions
        allow_connect = Direction.OUT in rule.directions
        if not allow_bind and not allow_connect:
            continue
        ports = rule.mask.ports
        if isinstance(ports, range):
            for p in ports:
                if 0 <= p <= 65535:
                    merge(p, allow_bind, allow_connect)
        else:
            for p in ports:
                merge(p, allow_bind, allow_connect)

    all_ports = [(port, b, c) for port, (b, c) in sorted(port_access.items())]
    logger.debug(f"{all_ports=}")
    return all_ports


def _get_critical_dns_paths() -> list[str]:
    # Essential files for name resolution
    base_files: list[str] = [
        "/etc/hosts",
        "/etc/resolv.conf",
        "/etc/nsswitch.conf",
        "/lib",
        "/usr/lib",
    ]

    resolved_paths: set[str] = set()
    for p in base_files:
        path_obj = Path(p)
        if path_obj.exists():
            resolved_paths.add(str(path_obj.resolve()))
            # Also add the parent directory for some NSS modules
            resolved_paths.add(str(path_obj.parent.resolve()))

    return list(resolved_paths)


def _apply_landlock(
    paths: list[tuple[str, bool]],
    net_ports: list[tuple[int, bool, bool]] | None = None,
) -> None:
    """Apply Landlock rules from paths and optional network port rules.

    paths: list of (path, write) for filesystem access.
    net_ports: optional list of (port, allow_bind, allow_connect) for TCP.
      When not None, network is restricted (ABI v4+): only listed ports/actions
      are allowed. When None, network is not restricted by Landlock.
    On failure (e.g. ENOSYS) raise or skip and caller may fallback.
    """
    abi = _get_landlock_abi_version()
    handled_net = 0
    if net_ports is not None and abi >= 4:
        handled_net = HANDLED_ACCESS_NET

    # Restrict handled FS rights to what the kernel ABI supports (forward compat).
    handled_fs = HANDLED_ACCESS_FS
    if abi < 2:
        handled_fs &= ~LANDLOCK_ACCESS_FS_REFER
    if abi < 3:
        handled_fs &= ~LANDLOCK_ACCESS_FS_TRUNCATE

    attr = LandlockRulesetAttr(
        handled_access_fs=handled_fs,
        handled_access_net=handled_net,
        scoped=0,
    )
    fd = syscall(
        _LANDLOCK_CREATE_RULESET,
        ctypes.byref(attr),
        c_size_t(ctypes.sizeof(attr)),
        c_uint32(0),
    )
    if fd < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"landlock_create_ruleset: errno {errno}")

    try:
        # Add DNS resolver
        paths.append((str(Path("/etc/resolv.conf").resolve().parent), False))
        paths.append((str(Path("/etc/resolv.conf").parent), False))

        for path, write in paths:
            path = os.path.normpath(path)
            if not path or path == ".":
                path = os.getcwd()
            elif not os.path.isabs(path):
                path = os.path.abspath(path)
            allowed = (ACCESS_RW if write else ACCESS_RO) & handled_fs
            parent_fd = libc.open(path.encode("utf-8"), O_PATH)
            if parent_fd < 0:
                errno = ctypes.get_errno()
                logger.warning("Landlock: cannot open path %s: errno %s", path, errno)
                continue
            try:
                path_attr = LandlockPathBeneathAttr(
                    allowed_access=allowed,
                    parent_fd=parent_fd,
                )
                ret = syscall(
                    _LANDLOCK_ADD_RULE,
                    fd,
                    c_uint32(LANDLOCK_RULE_PATH_BENEATH),
                    ctypes.byref(path_attr),
                    c_uint32(0),
                )
                logger.debug(f"{path=} {allowed=}")
                if ret != 0:
                    errno = ctypes.get_errno()
                    logger.warning(
                        "Landlock: landlock_add_rule for %s failed: errno %s",
                        path,
                        errno,
                    )
            finally:
                libc.close(parent_fd)

        if handled_net and net_ports is not None:
            for port, allow_bind, allow_connect in net_ports:
                access = 0
                if allow_bind:
                    access |= LANDLOCK_ACCESS_NET_BIND_TCP
                if allow_connect:
                    access |= LANDLOCK_ACCESS_NET_CONNECT_TCP
                if not access:
                    continue
                net_attr = LandlockNetPortAttr(
                    allowed_access=access,
                    port=port,
                )
                ret = syscall(
                    _LANDLOCK_ADD_RULE,
                    fd,
                    c_uint32(LANDLOCK_RULE_NET_PORT),
                    ctypes.byref(net_attr),
                    c_uint32(0),
                )
                if ret != 0:
                    errno = ctypes.get_errno()
                    logger.warning(
                        "Landlock: landlock_add_rule for port %s failed: errno %s",
                        port,
                        errno,
                    )

        ret = syscall(_LANDLOCK_RESTRICT_SELF, fd, c_uint32(0))
        if ret != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, f"landlock_restrict_self: errno {errno}")
    finally:
        libc.close(fd)


def landlock_user_available() -> bool:
    """Return True if Landlock is available on this system (Linux 5.13+)."""
    return _landlock_available()


def _collect_landlock_paths(all_rules: AllRules, temp: Path, cwd: str) -> list[tuple[str, str]]:
    """Build list of (path, 'ro'|'rw') for the Landlock launcher config."""
    path_to_access: dict[str, str] = {}

    def add(path: str, access: str) -> None:
        path = os.path.normpath(path)
        if not path or path == ".":
            path = cwd
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        if path in path_to_access and path_to_access[path] == "rw":
            return
        if path in path_to_access and access == "rw":
            path_to_access[path] = "rw"
            return
        if path not in path_to_access:
            if os.path.exists(path) or path == cwd or path == str(temp):
                path_to_access[path] = access

    # System paths required to run Python and runtime (read-only)
    for p in ["/bin", "/usr", "/lib", "/lib64", "/etc"]:
        if os.path.exists(p):
            add(p, "ro")
    # /dev (e.g. /dev/shm for multiprocessing semaphores) - read-write for runtime
    if os.path.exists("/dev"):
        add("/dev", "rw")

    # Python interpreter and library paths
    add(os.path.dirname(os.path.realpath(sys.executable)), "ro")
    for p in sys.path:
        if p and os.path.exists(p):
            add(p, "ro")
    if hasattr(site, "getsitepackages"):
        for p in site.getsitepackages():
            if p and os.path.exists(p):
                add(p, "ro")

    # Current directory and temp (for pipe) - read-write
    add(cwd, "rw")
    add(str(temp), "rw")

    # File rules: FSExposeRule paths as read-only or read-write
    for rule in all_rules.file_rules:
        if isinstance(rule, FSExposeRule):
            access = "rw" if rule.write else "ro"
            add(rule.path, access)
        # IgnoreRule: no path to add for Landlock (filtering is semantic)

    return list(path_to_access.items())


class LandlockSSEDaemon(SubProcessDaemon):
    """Subprocess daemon that applies Landlock filesystem and network restrictions.

    The sandbox process has Landlock rules applied from file_rules (paths) and
    socket_rules (TCP ports for bind/connect when kernel supports ABI v4).
    Communication is the same as SubProcessDaemon (SSE).
    """

    @override
    def update_rules_and_activate(
        self,
        *,
        envs: Envs,
        all_rules: AllRules,
        temp: Path,
    ) -> AllRules:
        """No rule transformation for Landlock."""
        if not _landlock_available():
            logger.error("Landlock not available (kernel < 5.13 or not Linux), exec without Landlock")
            sys.exit(-1)
        try:
            _set_no_new_privs()
            net_ports: list[tuple[int, bool, bool]] | None = (
                _collect_landlock_net_ports(all_rules.socket_rules) if all_rules.socket_rules else None
            )
            cwd = os.getcwd()
            temp_dir = Path(tempfile.gettempdir())
            path_tuples = _collect_landlock_paths(all_rules, temp_dir, cwd)
            paths_for_landlock = [(path, access == "rw") for path, access in path_tuples]
            _apply_landlock(paths_for_landlock, net_ports=net_ports)
        except OSError as e:
            if e.errno == 38:  # ENOSYS
                logger.exception("Landlock not supported, exec without Landlock")
            else:
                logger.exception("Landlock setup failed")
            sys.exit(-1)
        return all_rules
