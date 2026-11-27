# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Security proof tests for the file guard (AREA C of the cybedefend audit).

Marked run:    pytest tests/unit_tests/security_proofs/test_security_guards_files.py
Raw run:       pytest --runxfail tests/unit_tests/security_proofs/test_security_guards_files.py
"""

import os
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError
from pysandboxes.sb_types import ConfigLine
from tests.unit_tests.guard.test_guard_io import activate_guard_files_rules


def test_security_scandir_entry_stat_does_not_leak_through_a_symlink(tmp_path: Path) -> None:
    """``os.scandir()`` entries are wrapped in ``guard_files._DirEntry``, which delegates any
    attribute other than ``.path`` straight to the real, unwrapped ``os.DirEntry`` through
    ``__getattr__`` (pysandboxes/guard_files.py ``_DirEntry.__getattr__``). ``entry.stat()``
    (default ``follow_symlinks=True``), ``entry.is_file()``, ``entry.is_dir()`` and
    ``entry.inode()`` therefore never go through ``_apply_dest_to_src_rules``: a symlink
    inside an exposed, allowed directory that points at a file no rule exposes lets
    sandboxed code read that file's size, mtime and mode via ``entry.stat()``, the exact
    information ``os.stat()`` on the same path (by its own name or through the symlink)
    correctly refuses with ``RuleFileNotFoundError``. One listing of an otherwise ordinary
    exposed directory discloses the existence and metadata of anything on the host a
    symlink there is made to point at.
    """
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    secret = secret_dir / "secret.txt"
    secret.write_text("TOP SECRET CONTENT")

    exposed = tmp_path / "exposed"
    exposed.mkdir()
    (exposed / "escape").symlink_to(secret)

    activate_guard_files_rules([ConfigLine(f"expose-rw={exposed}", Path(), 0)])

    # Control: the guard refuses to even confirm the secret exists, by its real name
    # or through the symlink that an exposed, allowed directory holds.
    with pytest.raises(RuleFileNotFoundError):
        os.stat(secret)
    with pytest.raises(RuleFileNotFoundError):
        os.stat(exposed / "escape")

    # Guarantee under test: a directory listing of an exposed directory must not let the
    # caller learn anything about a file the rules hide, whatever name is used to reach it.
    with os.scandir(exposed) as it:
        entries = list(it)
    assert len(entries) == 1
    with pytest.raises(RuleFileNotFoundError):
        entries[0].stat()
    assert not entries[0].is_file()
    assert not entries[0].is_dir()
    assert entries[0].is_symlink()


def test_scandir_entries_of_files_the_rules_expose_still_answer(tmp_path: Path) -> None:
    exposed = tmp_path / "exposed"
    exposed.mkdir()
    (exposed / "plain.txt").write_text("content")
    (exposed / "sub").mkdir()
    activate_guard_files_rules([ConfigLine(f"expose-rw={exposed}", Path(), 0)])

    with os.scandir(exposed) as it:
        entries = {entry.name: entry for entry in it}

    assert entries["plain.txt"].stat().st_size == len("content")
    assert entries["plain.txt"].is_file()
    assert entries["sub"].is_dir()
