# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What the smolvm guest sees of the host: a few shares, from which its init script binds exactly what the rules expose.

The VMM of smolvm gives a micro-VM a small number of virtio-fs devices, one per smolvm mount, so one mount per rule
does not scale. The guest instead receives one read-only share per top directory of the paths the rules expose,
binds each of those paths where the rules put it, masks what ``ignore=`` names, then detaches every share: only the
binds stay. A writable directory keeps a share of its own. The command then runs as the host user, with no
capability.
"""

import fnmatch
import logging
import os
import shlex
import sys
from collections.abc import Iterable, Mapping

from ..all_rules import AllRules
from ..guard_files import FSExposeRule, IgnoreRule

logger = logging.getLogger(__name__)

STAGE = "/.pysb"
# The image brings its own system: a host directory bound over one would replace the guest's libraries.
_IMAGE_OWNED = ("/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64", "/proc", "/dev", "/sys")
_LEFT_MOUNTED = 70
_WRONG_PYTHON = 72
# What smolvm refuses to share, after resolving links: it answers "protected system path" before the guest starts.
_REFUSED = ("/usr", "/etc", "/lib", "/lib64", "/bin", "/sbin", "/boot", "/sys", "/proc", "/dev", "/run", "/var/log")


def _strip(path: str) -> str:
    return path.rstrip("/") or "/"


def _host_interpreter_prefixes() -> set[str]:
    """The installation of the host's Python: the guest runs the image's, so exposing it would only cost a share."""
    return {os.path.realpath(prefix) for prefix in (sys.prefix, sys.base_prefix)}


def is_refused_by_smolvm(path: str) -> bool:
    """Tell whether smolvm refuses to share ``path``, links resolved."""
    real = os.path.realpath(path)
    return real in ("/", "/var") or _is_inside(real, _REFUSED)


def _is_inside(path: str, parents: Iterable[str]) -> bool:
    return any(path == parent or path.startswith(parent.rstrip("/") + "/") for parent in parents)


def exposures(all_rules: AllRules, *, extra_ro: Iterable[str] = ()) -> tuple[list[str], list[str]]:
    """Return the host paths the guest receives, ``(read_only, read_write)``; ``extra_ro`` is what the provider adds.

    A path exposed both ways stays read-only. A writable path must be a directory, as a share is one: a file is
    reported and exposed read-only. What the image owns, the host's interpreter and a missing path are left out, and
    so is a path smolvm refuses to share, which is reported.
    """
    write: dict[str, bool] = {}
    for rule in all_rules.file_rules:
        if not isinstance(rule, FSExposeRule):
            continue
        path = _strip(rule.path)
        if _is_inside(path, _IMAGE_OWNED) or _is_inside(os.path.realpath(path), _host_interpreter_prefixes()):
            continue
        if not os.path.exists(path):
            continue
        if is_refused_by_smolvm(path):
            logger.warning("smolvm refuses to share %s: not exposed to the guest", path)
            continue
        writable = rule.write
        if writable and not os.path.isdir(path):
            logger.warning("smolvm shares only directories read-write: %s is exposed read-only", path)
            writable = False
        write[path] = write.get(path, True) and writable
    ro = [path for path, writable in write.items() if not writable]
    rw = [path for path, writable in write.items() if writable]
    ro.extend(path for path in extra_ro if path not in ro and path not in rw)
    return ro, rw


def shares(ro: Iterable[str]) -> list[tuple[str, str]]:
    """Return ``(host directory, guest stage)`` of the read-only shares: one per top directory of the paths.

    The share is the deepest directory holding every path of its top directory, so no more of the host than needed
    is ever handed to the guest, and the root of the host never is.
    """
    groups: dict[str, list[str]] = {}
    for path in ro:
        directory = os.path.dirname(path) if os.path.isfile(path) else path
        groups.setdefault(directory.split("/")[1], []).append(directory)
    return [
        (os.path.commonpath(directories), f"{STAGE}/host{index}") for index, directories in enumerate(groups.values())
    ]


def volumes(ro: Iterable[str], rw: Iterable[str]) -> list[str]:
    """Return the ``-v`` flags: a read-only share per top directory, and one share per writable directory."""
    flags = [arg for host, stage in shares(ro) for arg in ("-v", f"{host}:{stage}:ro")]
    return flags + [arg for index, path in enumerate(rw) for arg in ("-v", f"{path}:{STAGE}/rw{index}")]


def mask_targets(all_rules: AllRules, cwd: str, exposed: list[str]) -> list[tuple[str, bool]]:
    """Return ``(path, is_directory)`` of what ``ignore=`` rules hide inside the exposed paths.

    Only the working directory and the exposed directories are searched. A path is matched by its base name, as in
    ``guard_files``.
    """
    patterns = [rule.source for rule in all_rules.file_rules if isinstance(rule, IgnoreRule)]
    if not patterns:
        return []
    targets: dict[str, bool] = {}
    for tree in dict.fromkeys(os.path.realpath(root) for root in [cwd, *exposed] if os.path.isdir(root)):
        for directory, directories, files in os.walk(tree):
            for name in directories + files:
                if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                    continue
                path = os.path.join(directory, name)
                target = os.path.realpath(path) if os.path.islink(path) else path
                if os.path.exists(target) and _is_inside(target, exposed):
                    targets[target] = os.path.isdir(target)
    return list(targets.items())


def _bind_read_only(path: str, source: str) -> str:
    q = shlex.quote
    if os.path.islink(path):
        return f"mkdir -p {q(os.path.dirname(path))} && ln -s {q(os.readlink(path))} {q(path)}"
    if os.path.isdir(path):
        prepare = f"mkdir -p {q(path)}"
    else:
        prepare = f"mkdir -p {q(os.path.dirname(path))} && touch {q(path)}"
    return f"{prepare} && mount --bind {q(source)} {q(path)} && mount -o remount,bind,ro {q(path)}"


def init_script(
    *,
    ro: list[str],
    rw: list[str],
    masks: list[tuple[str, bool]],
    cwd: str,
    uid: int,
    gid: int,
    env: Mapping[str, str],
    command: list[str],
    python_version: tuple[int, int],
) -> str:
    """Return the ``sh`` script the guest runs: check Python, bind the exposed paths, mask, detach the shares, run.

    The guest must run the Python of the host, as the guard code runs on the interpreter that wrote the config: a
    guest of another version stops with ``_WRONG_PYTHON`` before anything is bound. The binds come shallow first, and a
    path inside one already bound is skipped. A share the guest still holds after the detach stops it with
    ``_LEFT_MOUNTED`` before the command runs: the command never sees more than the rules expose. ``"$@"`` carries the
    arguments the caller appends to ``command``. The standard input, which carries the config, is handed to the user
    first: the guest opens it as ``/dev/stdin`` once it has no privilege left.
    """
    q = shlex.quote
    stage_of = {path: stage for host, stage in shares(ro) for path in ro if _is_inside(path, [host])}
    host_of = {stage: host for host, stage in shares(ro)}
    major, minor = python_version
    wanted = f"{major}.{minor}"
    probe = f"import sys; sys.exit(0 if sys.version_info[:2] == ({major}, {minor}) else 1)"
    lines = [
        "set -e",
        f"{q(command[0])} -c {q(probe)} || "
        f'{{ echo "smolvm: the guest does not run Python {wanted} as the host does: '
        f'build the image with PYTHON_VERSION={wanted}" >&2; exit {_WRONG_PYTHON}; }}',
        "mount --make-rprivate / 2>/dev/null || true",
    ]
    bound: list[str] = []
    for path in sorted(dict.fromkeys(ro), key=lambda p: len(p.split("/"))):
        if _is_inside(path, bound):
            continue
        stage = stage_of[path]
        lines.append(_bind_read_only(path, stage + path[len(host_of[stage]) :]))
        if os.path.isdir(path):
            bound.append(path)
    for index, path in enumerate(rw):
        lines.append(f"mkdir -p {q(path)} && mount --bind {STAGE}/rw{index} {q(path)}")
    for path, is_directory in masks:
        lines.append(f"mount -t tmpfs -o ro tmpfs {q(path)}" if is_directory else f"mount --bind /dev/null {q(path)}")
    stages = [stage for _, stage in shares(ro)] + [f"{STAGE}/rw{index}" for index in range(len(rw))]
    lines.extend(f"while umount -l {stage} 2>/dev/null; do :; done" for stage in stages)
    lines.append(
        f'if grep -q " {STAGE}/" /proc/self/mountinfo; then echo "smolvm: a share is still mounted" >&2; '
        f"exit {_LEFT_MOUNTED}; fi"
    )
    lines.append(f"chown {uid}:{gid} /proc/self/fd/0")
    lines.append(f"cd {q(cwd)} 2>/dev/null || {{ mkdir -p {q(cwd)} && cd {q(cwd)}; }}")
    drop = ["setpriv", f"--reuid={uid}", f"--regid={gid}", "--clear-groups", "--bounding-set=-all", "--inh-caps=-all"]
    clean_env = [f"{key}={q(value)}" for key, value in env.items()]
    lines.append(" ".join(["exec", *drop, "--no-new-privs", "env", "-i", *clean_env, *(q(c) for c in command), '"$@"']))
    return "\n".join(lines) + "\n"
