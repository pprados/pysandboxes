# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Guard denying calls to sensitive functions.

Import rights and call rights are distinct: a module may be importable
while some of its functions must stay unreachable. This guard denies
calls to a finite registry of sensitive functions, independently of
``python-import=``, and records attempted calls in learning mode.
"""

import logging
import sys

logger = logging.getLogger(__name__)

SENSITIVE_API: dict[str, tuple[str, ...]] = {
    "process-exec": (
        "os.system",
        "posix.system",
        "os.popen",
        "os.execv",
        "posix.execv",
        "os.execve",
        "posix.execve",
        "os.execl",
        "os.execle",
        "os.execlp",
        "os.execlpe",
        "os.execvp",
        "os.execvpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.posix_spawn",
        "posix.posix_spawn",
        "os.posix_spawnp",
        "posix.posix_spawnp",
        "os.fork",
        "posix.fork",
        "os.forkpty",
        "posix.forkpty",
        "subprocess.Popen",
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "_posixsubprocess.fork_exec",
        "pty.spawn",
        "pty.fork",
        "multiprocessing.Process.start",
    ),
    "process-control": (
        "os.kill",
        "posix.kill",
        "os.killpg",
        "posix.killpg",
        "os.nice",
        "posix.nice",
        "os.setpriority",
        "posix.setpriority",
        "os.abort",
        "posix.abort",
        "os._exit",
        "posix._exit",
        "os.setsid",
        "posix.setsid",
        "os.setpgid",
        "posix.setpgid",
        "os.setpgrp",
        "posix.setpgrp",
        "signal.signal",
        "_signal.signal",
        "signal.alarm",
        "_signal.alarm",
        "signal.setitimer",
        "_signal.setitimer",
        "signal.raise_signal",
        "_signal.raise_signal",
        "signal.pthread_kill",
        "_signal.pthread_kill",
        "resource.setrlimit",
        "resource.prlimit",
    ),
    "privileges": (
        "os.setuid",
        "posix.setuid",
        "os.setgid",
        "posix.setgid",
        "os.seteuid",
        "posix.seteuid",
        "os.setegid",
        "posix.setegid",
        "os.setreuid",
        "posix.setreuid",
        "os.setregid",
        "posix.setregid",
        "os.setgroups",
        "posix.setgroups",
        "os.chroot",
        "posix.chroot",
        "os.umask",
        "posix.umask",
    ),
    "threads": (
        "_thread.start_new_thread",
        "_thread.start_new",
        "_thread.start_joinable_thread",
        "threading._start_joinable_thread",
        "threading._start_new_thread",
        "threading.Thread.start",
        "_thread.interrupt_main",
        "threading.settrace",
        "threading.setprofile",
        "threading.stack_size",
        "_thread.stack_size",
    ),
    "native": (
        "ctypes.CDLL",
        "ctypes.PyDLL",
        "ctypes.memmove",
        "ctypes.cast",
        "ctypes.string_at",
        "mmap.mmap",
    ),
    "introspection": (
        "sys.settrace",
        "sys.setprofile",
        "sys.addaudithook",
        "gc.get_objects",
        "gc.get_referrers",
        "faulthandler.enable",
    ),
}

CATEGORIES: frozenset[str] = frozenset(SENSITIVE_API)

# The thread launch primitive moved between supported versions:
# 3.11-3.12 expose threading._start_new_thread, while 3.13 replaces it
# by threading._start_joinable_thread, the same object as
# _thread.start_joinable_thread. Both spellings are registered so a
# profile stays portable, and only the applicable ones are patched.
_PRE_313 = frozenset({"threading._start_new_thread"})
_FROM_313 = frozenset(
    {
        "threading._start_joinable_thread",
        "_thread.start_joinable_thread",
    }
)

OPTIONAL: frozenset[str] = _PRE_313 | _FROM_313
"""Entries whose absence is legitimate on some version or platform.

The integrity test fails on a missing entry unless it is listed here, so
a typo is still caught while a version difference is not a false alarm.
"""


def _not_applicable() -> frozenset[str]:
    """Return the entries this interpreter must not patch.

    ``guard_import._apply_patch`` calls ``getattr`` before invoking the
    factory, so a registered name absent from a module that *is*
    imported would raise at startup. Only ``threading`` is concerned:
    a module that cannot be imported at all is never patched.
    """
    if sys.version_info >= (3, 13):
        return _PRE_313
    return _FROM_313


_CATEGORY_OF: dict[str, str] = {
    qualname: category
    for category, qualnames in SENSITIVE_API.items()
    for qualname in qualnames
}


def all_qualnames() -> tuple[str, ...]:
    """Return every qualified name of the registry, in category order."""
    return tuple(_CATEGORY_OF)


def split_qualname(qualname: str) -> tuple[str, str]:
    """Split ``module.attr`` into its module and its attribute path.

    ``"threading.Thread.start"`` yields ``("threading",
    "Thread.start")``. The module is always the leading segment, matching
    ``guard_import._conv_patch_rules``.
    """
    module_name, _, attribute_path = qualname.partition(".")
    return module_name, attribute_path
