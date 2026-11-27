# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Security proof test for the ``unshare`` provider (AREA E of the cybedefend audit).

Marked run:    uv run pytest tests/unit_tests/security_proofs/test_security_linux_unshare_cwd.py
Raw run:       uv run pytest --runxfail tests/unit_tests/security_proofs/test_security_linux_unshare_cwd.py

A profile with no ``expose-ro=`` / ``expose-rw=`` rule for the sandbox's working directory
produces no ``FSExposeRule`` that covers it: loading ``py-sandbox=true\\nos-sandbox=unshare\\n
learn=false`` with no ``expose-*`` line gives an ``AllRules.file_rules`` that only names the
interpreter, the CA store and the safe devices, nothing under the working directory (checked by
hand against ``load_and_parse_config()``; ``EmptyRules.file_rules`` is the same, empty, baseline).
``UnshareSSEDaemon._prepare_unshare_config`` (``pysandboxes/remote/unshare_sse_daemon.py``) builds
``mounts_ro`` / ``mounts_rw`` from exactly those file rules, so it carries no entry for the working
directory either. Yet ``unshare_setup.main`` (step "F. Mount current directory",
``pysandboxes/remote/unshare_setup.py``) bind-mounts ``config.current_dir`` read-write
unconditionally, with no gate on any rule at all.

This contradicts:
- the project's own security model (AGENTS.md / ``wiki/security-model.md``: "Default deny-all,
  explicit whitelist via `.py-sandboxes` config files");
- ``landlock_daemon.py``'s ``_collect_landlock_paths``, which only ever grants the current
  directory through the file rules loop, with the comment "Grant write access to the current
  directory only through an explicit file rule";
- ``bwrap_sse_daemon.py``, which binds no path of the current directory automatically either;
- ``CHANGELOG.md``: "Allow `os.getcwd()` and `os.getcwdb()` to report the current directory
  without granting file access" -- the same working directory the OS layer then grants in full.

The Python-layer guard (``guard_files``) still enforces the profile's rules for ordinary Python
calls, so this is invisible to code that only uses ``open()``. The whole point of adding an OS
provider is native code and direct system calls (``wiki/os-providers.md``: "Hostile native code
... bwrap or unshare ... a path that is not exposed does not exist"): under ``os-sandbox=unshare``,
a C extension, a ``ctypes`` call or a child process writes or deletes every file under the working
directory the profile's ``expose-ro=`` rule leaves read-only, or that no ``expose-*`` rule names at
all, because the OS boundary grants it write access by default and the Python guard never sees the
native call. ``ignore=`` is unaffected: step G.2 (``unshare_setup.py``, "Apply ignore overlays")
masks an ignored path under the working directory at the OS level too, after step F.

This reproduces only when the working directory is not itself one of the host interpreter's
``sys.path`` entries: when it is (for instance running ``python -m pkg`` from that directory),
``UnshareSSEDaemon._prepare_unshare_config`` also puts it in ``mounts_ro`` for the interpreter's
own search path, and step G's later read-only remount then lands on top of step F's read-write
one. A console-script entry point (``sys.path[0]`` is the venv's own ``bin``) or a project with a
``src`` layout (only ``<project>/src`` ends up on ``sys.path``, not the project root) keep the
working directory writable regardless.

``tests/unit_tests/remote/test_unshare_setup_main.py::TestMounts::
test_the_current_directory_is_writable_and_user_mounts_follow_their_mode`` already asserts
today's behaviour (the current directory ends up mounted read-write); fixing this finding means
updating that test alongside the fix, to gate step F on an explicit rule the way landlock gates
its own equivalent grant.
"""

import os
import subprocess as subprocess_module
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote import unshare_setup
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="unshare_setup only runs on Linux")


def test_security_unshare_does_not_mount_cwd_rw_without_a_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """unshare must not grant write access to the working directory when no rule names it.

    Builds the ``UnshareSetupConfig`` through the real ``UnshareSSEDaemon._prepare_unshare_config``
    (the function a real ``.py-sandboxes`` with no ``expose-*`` rule for the project directory
    feeds), then drives the real ``unshare_setup.main()`` with every mount(2)/exec(2) call replaced
    by a recorder, and inspects the exact argv it built for the ``mount`` commands touching the
    working directory.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "secret.txt").write_text("do-not-touch")
    new_root = tmp_path / "chroot"
    new_root.mkdir()
    monkeypatch.chdir(project_dir)

    # EmptyRules.file_rules is empty, exactly what a profile with no expose-ro=/expose-rw= line
    # for the working directory produces (confirmed against a real `load_and_parse_config()` with
    # no such line).
    config, _dns_servers = UnshareSSEDaemon._prepare_unshare_config(
        SimpleNamespace(),  # type: ignore[arg-type]  # only ``self._ipv6 = ...`` is read off it
        EmptyRules,
        tmp_path / "pipe",
        str(new_root),
    )
    assert str(project_dir) not in [src for src, _dst in config.mounts_ro], (
        "precondition: the profile's own mount list must not already cover the working "
        "directory, or this proof would show a rule's effect, not the default's"
    )
    assert str(project_dir) not in [src for src, _dst in config.mounts_rw]
    config_path = tmp_path / "config.json"
    config_path.write_text(config.to_json())

    recorded_argv: list[list[str]] = []

    def record_run(cmd: list[str], check: bool = True, **kwargs: Any) -> None:
        recorded_argv.append(list(cmd))

    def record_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess_module.CompletedProcess[str]:
        recorded_argv.append(list(cmd))
        return subprocess_module.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(unshare_setup, "_run", record_run)
    monkeypatch.setattr(unshare_setup.subprocess, "run", record_subprocess_run)
    # main() execs into the sandbox at the very end; nothing in the function runs after that call.
    monkeypatch.setattr(unshare_setup.os, "execvp", lambda *a, **k: None)
    monkeypatch.setattr(unshare_setup.os, "chdir", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["unshare_setup", str(config_path), "--", "true"])

    ready_r, ready_w = os.pipe()
    os.write(ready_w, b"1")
    os.close(ready_w)
    # main() reads SLIRP_READY_FD from the environment and later replaces os.environ wholesale
    # with the sandbox's own envs (step J): swap the whole mapping instead of one variable, so
    # nothing of this process's real environment is at risk and nothing needs manual restore.
    monkeypatch.setattr(os, "environ", {"SLIRP_READY_FD": str(ready_r)})

    unshare_setup.main()  # closes ready_r itself, once it reads the readiness byte

    full_dst = str(new_root) + str(project_dir)
    ops_on_cwd = [argv for argv in recorded_argv if argv and argv[-1] == full_dst]
    # The guarantee: either nothing ever bind-mounted the working directory (a fix that only
    # creates the empty chroot directory for `env --chdir` to enter), or the last operation on it
    # is a read-only remount (a fix that mounts it, but not writable, by default).
    left_writable = bool(ops_on_cwd) and not (
        ops_on_cwd[-1][:2] == ["mount", "-o"] and "ro" in ops_on_cwd[-1][2].split(",")
    )

    assert not left_writable, (
        f"unshare grants write access to the working directory with no expose-rw= rule for it, "
        f"and no rule for it at all in this profile: the operations unshare_setup issued on it "
        f"were {ops_on_cwd!r}. landlock_daemon._collect_landlock_paths only grants the current "
        f"directory through an explicit file rule, and bwrap binds no path of it automatically "
        f"either: unshare should not grant write access to it by default."
    )
