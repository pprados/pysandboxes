# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""OCI runtime spec of a gVisor guest: the filesystem, environment and privilege boundary handed to ``runsc``."""

import fnmatch
import logging
import os
from collections.abc import Iterable
from typing import Any

from ..all_rules import AllRules
from ..guard_files import FSExposeRule, IgnoreRule

logger = logging.getLogger(__name__)

_SYSTEM_PATHS = ("/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64")
_GUEST_OWNED = ("/dev", "/proc")


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
    return any(path.rstrip("/") == owned or path.startswith(owned + "/") for owned in _GUEST_OWNED)


def _is_inside(path: str, exposed: list[str]) -> bool:
    """Tell whether ``path`` is one of the exposed paths, or below one.

    post: path not in exposed or __return__
    post: exposed or not __return__
    """
    return any(path == e or path.startswith(e.rstrip("/") + "/") for e in exposed)


def _is_writable_by_a_rule(all_rules: AllRules, path: str) -> bool:
    """Tell whether an ``expose-rw`` rule names ``path``.

    post: not __return__ or any(isinstance(r, FSExposeRule) and r.write for r in all_rules.file_rules)
    """
    return any(
        isinstance(rule, FSExposeRule) and rule.write and _strip(rule.path) == path for rule in all_rules.file_rules
    )


def exposures(
    all_rules: AllRules,
    *,
    runtime_paths: Iterable[str],
    guest_dir: str,
) -> tuple[list[str], list[str]]:
    """Return the host paths exposed ``(read_only, read_write)``: the system, the interpreter, the rules, the config.

    ``guest_dir`` holds the config the guest reads, and nothing else: the run directory, with the spec, the
    filter and the config pipe, is never exposed. Only a rule makes a path writable.
    A rule naming ``/dev`` or ``/proc`` cannot be honoured in the guest, which has its own: it is reported, as
    binding the host one would show the guest the host.
    A path missing on the host is left out, as ``runsc`` refuses to start on a bind of a missing source.

    pre: guest_dir.startswith('/')
    post: guest_dir in __return__[0] and guest_dir not in __return__[1]
    post: len(set(__return__[0])) == len(__return__[0])
    post: len(set(__return__[1])) == len(__return__[1])
    post: not any(_is_guest_owned(p) for p in __return__[0] + __return__[1])
    post: all(_is_writable_by_a_rule(all_rules, path) for path in __return__[1])
    """
    ro = [p for p in _SYSTEM_PATHS if os.path.exists(p)]
    ro.extend(p for p in runtime_paths if os.path.exists(p))
    ro.append(guest_dir)
    rw: list[str] = []
    for rule in all_rules.file_rules:
        if not isinstance(rule, FSExposeRule):
            continue
        path = _strip(rule.path)
        if _is_guest_owned(path):
            logger.warning("gvisor cannot expose %s: the guest has its own /dev and /proc; not enforced", path)
        elif os.path.exists(path):
            (rw if rule.write and path != guest_dir else ro).append(path)
    return list(dict.fromkeys(ro)), list(dict.fromkeys(rw))


def mask_targets(all_rules: AllRules, current_dir: str, exposed: list[str]) -> list[tuple[str, bool]]:
    """Return ``(path, is_directory)`` of what ``ignore=`` rules hide inside the exposed paths.

    The trees searched are the working directory and the directories the rules expose: not the system or
    the interpreter, which no rule names and which can be large. A path is matched by the base name, as in
    ``guard_files``. A symlink is masked through the file it points to, as ``runsc`` refuses a symlink as a
    mount destination.

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


def _bind(source: str, destination: str, *, write: bool) -> dict[str, Any]:
    return {
        "destination": destination,
        "type": "bind",
        "source": source,
        "options": ["rbind", "rw" if write else "ro"],
    }


def build_oci_spec(
    *,
    rootfs: str,
    args: list[str],
    env: dict[str, str],
    mounts_ro: list[str],
    mounts_rw: list[str],
    masks: list[tuple[str, bool]],
    empty_file: str,
    cwd: str,
    mount_proc: bool = True,
) -> dict[str, Any]:
    """Return the OCI spec of a guest that sees only what the rules expose.

    Args:
        rootfs: Empty directory used as the read-only root of the guest.
        args: Command run in the guest.
        env: The whole environment of the guest. Nothing else is added.
        mounts_ro: Host paths exposed read-only, at the same path in the guest.
        mounts_rw: Host paths exposed read-write, at the same path in the guest.
        masks: ``(path, is_directory)`` hidden inside the exposed paths.
        empty_file: Empty host file bound over a masked file.
        cwd: Working directory of the command.
        mount_proc: Whether to mount ``/proc``.

    The guest holds no capability and cannot gain one. It runs in the network namespace of the process
    that launches ``runsc``, which is private and filtered by then, so the spec adds no network namespace.
    A path exposed both ways is read-only: the narrower right wins. A mask comes after the exposures, so it
    covers what they bind.

    pre: len(args) > 0
    pre: cwd.startswith('/')
    pre: all(key and '=' not in key for key in env)
    pre: all(path.startswith('/') for path in mounts_ro + mounts_rw)
    post: __return__['root']['readonly'] is True
    post: __return__['process']['noNewPrivileges'] is True
    post: all(caps == [] for caps in __return__['process']['capabilities'].values())
    post: len(__return__['process']['env']) == len(env)
    post: all(ns['type'] != 'network' for ns in __return__['linux']['namespaces'])
    post: len(__return__['mounts']) >= len(masks)
    """
    mounts: list[dict[str, Any]] = [{"destination": "/tmp", "type": "tmpfs", "source": "tmpfs", "options": ["rw"]}]
    if mount_proc:
        mounts.append({"destination": "/proc", "type": "proc", "source": "proc"})
    read_only_by_path = {path: False for path in mounts_rw}
    read_only_by_path.update({path: True for path in mounts_ro})
    for path, read_only in sorted(read_only_by_path.items()):
        mounts.append(_bind(path, path, write=not read_only))
    for path, is_directory in masks:
        if is_directory:
            mounts.append({"destination": path, "type": "tmpfs", "source": "tmpfs", "options": ["ro"]})
        else:
            mounts.append(_bind(empty_file, path, write=False))
    return {
        "ociVersion": "1.0.0",
        "process": {
            "terminal": False,
            "user": {"uid": 0, "gid": 0},
            "args": args,
            "env": [f"{key}={value}" for key, value in env.items()],
            "cwd": cwd,
            "capabilities": {name: [] for name in ("bounding", "effective", "permitted", "inheritable", "ambient")},
            "noNewPrivileges": True,
        },
        "root": {"path": rootfs, "readonly": True},
        "mounts": mounts,
        "linux": {"namespaces": [{"type": name} for name in ("pid", "ipc", "uts", "mount")]},
    }
