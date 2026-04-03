# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Landlock-based daemon for OS-level sandboxing.

This module implements a sandbox daemon that uses the Linux Landlock LSM
to restrict filesystem access of the sandbox process. It extends
BaseSubProcessDaemon and wraps the main_sandbox command with a Landlock
launcher that applies rules derived from the configuration file rules.
"""

import json
import logging
import os
import site
import sys
from pathlib import Path
from typing import Any, override

from .sse_client_subprocess_daemon import BaseSubProcessDaemon, SubProcessDaemon
from ..all_rules import AllRules
from ..guard_files import BindRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..sb_types import Args, ConfigLines, Envs

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

# Handled access: all FS rights we may allow (ABI v1)
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
)

ACCESS_RO = (
    LANDLOCK_ACCESS_FS_EXECUTE
    | LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
)
ACCESS_RW = (
    ACCESS_RO
    | LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_SYM
    | LANDLOCK_ACCESS_FS_REFER
)

# Syscall numbers (Linux x86_64 and aarch64 common)
try:
    import ctypes
    from ctypes import Structure, c_int, c_size_t, c_uint32, c_void_p

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


def _set_no_new_privs() -> None:
    libc.prctl.argtypes = [c_int, c_uint32, c_uint32, c_uint32, c_uint32]
    libc.prctl.restype = c_int
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_NO_NEW_PRIVS) failed")


def _apply_landlock(paths: list[tuple[str, bool]]) -> None:
    """Apply Landlock rules from list of (path, 'ro'|'rw') then return.
    On failure (e.g. ENOSYS) raise or skip and caller may fallback.
    """
    attr = LandlockRulesetAttr(
        handled_access_fs=HANDLED_ACCESS_FS,
        handled_access_net=0,
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
        for path, write in paths:
            path = os.path.normpath(path)
            if not path or path == ".":
                path = os.getcwd()
            elif not os.path.isabs(path):
                path = os.path.abspath(path)
            allowed = ACCESS_RW if write else ACCESS_RO
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
                if ret != 0:
                    errno = ctypes.get_errno()
                    logger.warning(
                        "Landlock: landlock_add_rule for %s failed: errno %s",
                        path,
                        errno,
                    )
            finally:
                libc.close(parent_fd)

        ret = syscall(_LANDLOCK_RESTRICT_SELF, fd, c_uint32(0))
        if ret != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, f"landlock_restrict_self: errno {errno}")
    finally:
        libc.close(fd)
def landlock_user_available() -> bool:
    """Return True if Landlock is available on this system (Linux 5.13+)."""
    return _landlock_available()


def _collect_landlock_paths(
    all_rules: AllRules, temp: Path, cwd: str
) -> list[tuple[str, str]]:
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

    # File rules: BindRule allows source (and dest) with write or ro
    for rule in all_rules.file_rules:
        if isinstance(rule, BindRule):
            access = "rw" if rule.write else "ro"
            add(rule.source, access)
            dest = rule.dest if rule.dest is not None else rule.source
            if dest != rule.source:
                add(dest, access)
        # IgnoreRule: no path to add for Landlock (filtering is semantic)

    return list(path_to_access.items())


class LandlockSSEDaemon(SubProcessDaemon):
    """Subprocess daemon that applies Landlock filesystem restrictions.

    The sandbox process is started via landlock_launcher, which applies
    Landlock rules derived from file_rules and essential paths, then
    exec's main_sandbox. Communication is the same as SubProcessDaemon (SSE).
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
            logger.error(
                "Landlock not available (kernel < 5.13 or not Linux), exec without Landlock"
            )
            sys.exit(-1)
        try:
            _set_no_new_privs()
            _apply_landlock([(r.source,r.write) for r in all_rules.file_rules if isinstance(r,BindRule)])
        except OSError as e:
            if e.errno == 38:  # ENOSYS
                logger.exception("Landlock not supported, exec without Landlock")
            else:
                logger.exception("Landlock setup failed")
            sys.exit(-1)
        return all_rules

