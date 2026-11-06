# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What the libkrun guest sees of the host: the paths its root is built from, and the ones the rules hide.

The micro-VM boots on the host root, shared read-only. The guest's init script builds a new, smaller root out of
it and switches to it, so nothing a rule does not name stays reachable.
"""

import fnmatch
import logging
import os
import site
import sys
from pathlib import Path

from ..all_rules import AllRules
from ..guard_files import FSExposeRule, IgnoreRule
from ..tools import follow_links_executable

logger = logging.getLogger(__name__)

_SYSTEM_PATHS = ("/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64")
_GUEST_OWNED = ("/dev", "/proc")
# The guest's own /dev has these: a rule naming one is met, so it is not worth a warning.
_STANDARD_DEVICES = ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom", "/dev/tty", "/dev/full")


def _strip(path: str) -> str:
    """Drop the trailing separator a directory rule carries, keeping the root as it is.

    post: __return__ == '/' or not __return__.endswith('/')
    post: __return__ != ''
    """
    return path.rstrip("/") or "/"


def _is_guest_owned(path: str) -> bool:
    """Tell whether ``path`` is ``/dev`` or ``/proc``, or below one: the guest has its own, which a bind would hide.

    post: not __return__ or path.rstrip('/').split('/')[1] in ('dev', 'proc')
    """
    return any(path == owned or path.startswith(owned + "/") for owned in _GUEST_OWNED)


def _is_inside(path: str, exposed: list[str]) -> bool:
    """Tell whether ``path`` is one of the exposed paths, or below one.

    post: path not in exposed or __return__
    post: exposed or not __return__
    """
    return any(path == e or path.startswith(e.rstrip("/") + "/") for e in exposed)


def runtime_paths() -> list[str]:
    """The interpreter, its libraries and the directories ``.pth`` files add to ``sys.path``."""
    chain: set[Path] = set()
    follow_links_executable(Path(sys.executable), chain)
    paths = [str(p) for p in chain] + [str(Path(sys.executable).resolve(strict=True))]
    paths += [p for p in sys.path if p and os.path.isdir(p)]
    paths += [p for p in site.getsitepackages() if os.path.isdir(p)]
    return list(dict.fromkeys(paths))


def exposures(all_rules: AllRules, *, runtime: list[str], run_dir: str) -> tuple[list[str], list[str]]:
    """Return the host paths the guest root is built from, ``(read_only, read_write)``.

    The read-only ones are the system, the interpreter and what the rules expose read-only; only a rule makes a path
    writable. A path named both ways stays read-only, and a path missing on the host is left out. ``run_dir`` is the
    host run directory, which the guest receives through a share of its own and never through the root.

    post: len(set(__return__[0])) == len(__return__[0])
    post: len(set(__return__[1])) == len(__return__[1])
    post: not any(_is_guest_owned(p) for p in __return__[0] + __return__[1])
    post: not set(__return__[0]) & set(__return__[1])
    """
    ro = [p for p in _SYSTEM_PATHS if os.path.exists(p)]
    ro.extend(p for p in runtime if os.path.exists(p))
    rw: list[str] = []
    for rule in all_rules.file_rules:
        if not isinstance(rule, FSExposeRule):
            continue
        path = _strip(rule.path)
        if _is_guest_owned(path):
            (logger.debug if path in _STANDARD_DEVICES else logger.warning)(
                "libkrun cannot expose %s: the guest has its own /dev and /proc; not enforced", path
            )
        elif path == run_dir or not os.path.exists(path):
            continue
        elif rule.write and os.path.isdir(path):
            rw.append(path)
        else:
            ro.append(path)
    ro = list(dict.fromkeys(ro))
    return ro, [p for p in dict.fromkeys(rw) if p not in ro]


def mask_targets(all_rules: AllRules, current_dir: str, exposed: list[str]) -> list[tuple[str, bool]]:
    """Return ``(path, is_directory)`` of what ``ignore=`` rules hide inside the exposed paths.

    Only the working directory and the directories the rules expose are searched, not the system or the interpreter.
    A path is matched by its base name, as in ``guard_files``.

    pre: current_dir.startswith('/')
    post: len({path for path, _ in __return__}) == len(__return__)
    post: all(_is_inside(path, exposed) for path, _ in __return__)
    post: all_rules.file_rules or __return__ == []
    """
    patterns = [r.source for r in all_rules.file_rules if isinstance(r, IgnoreRule)]
    if not patterns:
        return []
    roots = [current_dir] + [_strip(r.path) for r in all_rules.file_rules if isinstance(r, FSExposeRule)]
    targets: dict[str, bool] = {}
    for tree in dict.fromkeys(os.path.realpath(root) for root in roots if os.path.isdir(root)):
        for directory, directories, files in os.walk(tree):
            for name in directories + files:
                if not any(fnmatch.fnmatch(name, p) for p in patterns):
                    continue
                path = os.path.join(directory, name)
                target = os.path.realpath(path) if os.path.islink(path) else path
                if os.path.exists(target) and _is_inside(target, exposed):
                    targets[target] = os.path.isdir(target)
    return list(targets.items())
