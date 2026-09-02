# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Regression tests for the escapes closed in the guards.

Each test pins a bypass that used to work:
- a symlink inside an exposed directory pointing outside it,
- an empty ``python-import`` rule set behaving like a wildcard,
- an AF_UNIX socket path exempted from every rule.
"""

import posix
from pathlib import Path
from typing import Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes import guard_import
from pysandboxes.e import (
    RuleFileNotFoundError,
    RuleModuleNotFoundError,
    RuleSocketConnectionRefusedError,
)
from pysandboxes.guard_files import _apply_dest_to_src_rules, _wrap_os_symlink
from pysandboxes.guard_socket import _check_unix_socket
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import _deactivate_all_rules, activate_guard_files_rules


@pytest.fixture
def exposed_dir(tmp_path: Path) -> Iterator[Path]:
    """Expose ``tmp_path/allowed`` read-write, with a secret outside it.

    The working directory is exposed read-only as well, so that pytest can
    still chdir back at teardown; the secret lives under ``tmp_path``, which
    stays out of scope.
    """
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (tmp_path / "secret.txt").write_text("classified\n")
    activate_guard_files_rules(
        [
            ConfigLine(f"expose-rw={allowed}", Path(), 0),
            ConfigLine(f"expose-ro={Path.cwd()}", Path(), 0),
        ]
    )
    yield allowed
    _deactivate_all_rules()


@pytest.fixture
def import_rules() -> Iterator[None]:
    """Restore the import rules after a test tampered with them."""
    saved = guard_import._rules
    yield
    guard_import._rules = saved


def _make_symlink(target: str, link: Path) -> None:
    """Create a symlink with the unpatched ``os.symlink``.

    Whether the guard patches are installed depends on which tests ran
    before, so go around them: these tests check the authorization
    decision, not the creation path.

    ``posix.symlink`` is that way in: the patch table names ``os.symlink``
    (``guard_files.py:1480``) and leaves the ``posix`` module alone, so the
    attribute there is still the original object. The guarded callable no
    longer carries a ``__wrapped__`` back-reference (see ``guard_wraps``).
    """
    posix.symlink(target, str(link))


@pytest.mark.parametrize("target", ["absolute", "relative"])
def test_symlink_leaving_the_exposed_dir_is_denied(exposed_dir: Path, target: str) -> None:
    """A link inside the scope must not authorize its outside target."""
    secret = exposed_dir.parent / "secret.txt"
    link = exposed_dir / f"{target}.txt"
    _make_symlink(str(secret) if target == "absolute" else "../secret.txt", link)

    # The target itself is out of scope...
    assert _apply_dest_to_src_rules(str(secret), write=False) == (None, None)
    # ...and so is the link that resolves to it, though its own path is in.
    assert _apply_dest_to_src_rules(str(link), write=False) == (None, None)


@pytest.mark.parametrize("target", ["absolute", "relative"])
def test_creating_a_symlink_out_of_scope_is_refused(exposed_dir: Path, target: str) -> None:
    """``os.symlink`` must validate its target, in either form."""
    secret = exposed_dir.parent / "secret.txt"
    wrapped = _wrap_os_symlink(lambda src, dst, **kwargs: "created")

    with pytest.raises(RuleFileNotFoundError):
        wrapped(
            str(secret) if target == "absolute" else "../secret.txt",
            str(exposed_dir / f"link_{target}.txt"),
        )


def test_creating_a_symlink_inside_the_scope_is_allowed(
    exposed_dir: Path,
) -> None:
    wrapped = _wrap_os_symlink(lambda src, dst, **kwargs: "created")
    (exposed_dir / "target.txt").write_text("y\n")

    assert wrapped("target.txt", str(exposed_dir / "link.txt")) == "created"


def test_regular_file_in_scope_keeps_its_unresolved_path(
    exposed_dir: Path,
) -> None:
    """The decision uses the canonical path, the returned path stays raw."""
    target = exposed_dir / "ok.txt"

    remapped, rule = _apply_dest_to_src_rules(str(target), write=True)

    assert rule is None
    assert remapped == str(target)


def test_no_import_rule_denies_every_module(import_rules: None) -> None:
    """An empty rule set is a deny-all, not a missing filter."""
    guard_import._rules = ()

    assert not guard_import._is_import_allowed("os")
    assert not guard_import._is_import_allowed("logging")


def test_wildcard_import_rule_allows_every_module(import_rules: None) -> None:
    guard_import._rules = ("*",)

    assert guard_import._is_import_allowed("anything")


def test_listed_module_is_allowed(import_rules: None) -> None:
    guard_import._rules = ("httpx",)

    assert guard_import._is_import_allowed("httpx")
    assert not guard_import._is_import_allowed("socket")


def test_own_package_is_matched_exactly(import_rules: None) -> None:
    """``pysandboxesx`` on sys.path must not pass as this package."""
    guard_import._rules = ()

    assert guard_import._is_import_allowed("pysandboxes")
    assert not guard_import._is_import_allowed("pysandboxesx")


def test_find_spec_denies_a_module_outside_the_rules(import_rules: None) -> None:
    """The finder's own deny branch, not just the predicate it calls.

    ctypes reaches the filesystem straight through libc and subprocess
    reaches it through a child process, so neither is stopped by the file
    rules: the import rule is what closes them. subprocess is already in
    sys.modules by the time the guard arms, so a cached entry must not keep
    it reachable either.
    """
    guard_import._rules = ("os",)
    # The deny branch raises before delegating, so it needs no real finder.
    finder = guard_import.GuardFinder([])

    for module_name in ("ctypes", "subprocess", "socket"):
        with pytest.raises(RuleModuleNotFoundError):
            finder.find_spec(module_name, None, None)


def test_unix_socket_out_of_scope_is_denied(exposed_dir: Path) -> None:
    with pytest.raises(RuleSocketConnectionRefusedError):
        _check_unix_socket("/var/run/docker.sock", write=False, operation="connect")


def test_unix_socket_in_scope_is_allowed(exposed_dir: Path) -> None:
    _check_unix_socket(str(exposed_dir / "app.sock"), write=True, operation="bind")
