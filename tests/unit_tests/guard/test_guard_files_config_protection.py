# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""NA1 regression: sandboxed code must not be able to widen its own permissions by
rewriting the active ``.py-sandboxes`` (or the learning output file), even when
that file sits inside an ``expose-rw`` directory, and even across a later
re-activation of the same profile -- the real daemon re-reads the file from disk
on every ``with sandboxes()``, so a rule appended during one run would otherwise
apply to the next.

Goes through the real activation path: ``load_and_parse_config`` then
``py_sandbox.activate_sandboxes``, the exact function ``remote/main_sandbox.py``
calls once armed in a real daemon. ``rules_provider="none"`` keeps the OS
provider out of it (NA1 is about the Python guard), matching how
``remote/main_sandbox.py`` runs the QEMU guest's own user program in-process.
"""

import importlib
from pathlib import Path
from typing import Any, Iterator

import pytest

from pysandboxes import guard_api, guard_envs, guard_eval, guard_files, guard_import, guard_socket
from pysandboxes.e import RuleFileNotFoundError, RulePermissionError
from pysandboxes.lifecycle import _reset_for_tests, arm
from pysandboxes.py_sandbox import activate_sandboxes, load_and_parse_config
from pysandboxes.tools import set_is_in_sandbox


@pytest.fixture(autouse=True)
def _restore_patched_functions() -> Iterator[None]:
    """``activate_sandboxes`` patches the stdlib for good (``os.system``...); later tests expect the originals."""
    saved: list[tuple[Any, str, Any]] = []
    for guard in (guard_envs, guard_files, guard_socket, guard_import, guard_api, guard_eval):
        for qualname in guard.patch_rules(False):
            module_name, _, attribute_path = qualname.partition(".")
            try:
                owner: Any = importlib.import_module(module_name)
                *parents, name = attribute_path.split(".")
                for node in parents:
                    owner = getattr(owner, node)
                saved.append((owner, name, getattr(owner, name)))
            except (ImportError, AttributeError, ValueError):
                continue
    yield
    for owner, name, original in saved:
        try:
            setattr(owner, name, original)
        except (AttributeError, TypeError):
            pass


def _activate(config_path: Path) -> None:
    """Reload the profile from disk and arm the guards, like a real daemon does
    on every activation."""
    _reset_for_tests()
    all_rules = load_and_parse_config(config_path=config_path)
    activate_sandboxes(all_rules, rules_provider="none")
    set_is_in_sandbox(True)
    arm()


def _disarm() -> None:
    set_is_in_sandbox(False)
    _reset_for_tests()


def test_open_for_write_on_the_active_config_is_denied(tmp_path: Path) -> None:
    config = tmp_path / ".py-sandboxes"
    config.write_text(f"py-sandbox=true\nexpose-rw={tmp_path}\nos-sandbox=none\nlearn=false\n")
    before = config.read_text()

    _activate(config)
    try:
        with pytest.raises(RulePermissionError):
            open(config, "a").close()
    finally:
        _disarm()

    assert config.read_text() == before


def test_unlink_and_rename_of_the_active_config_are_denied(tmp_path: Path) -> None:
    import os

    config = tmp_path / ".py-sandboxes"
    config.write_text(f"py-sandbox=true\nexpose-rw={tmp_path}\nos-sandbox=none\nlearn=false\n")

    _activate(config)
    try:
        with pytest.raises(RulePermissionError):
            os.unlink(config)
        with pytest.raises(RulePermissionError):
            os.rename(config, tmp_path / "renamed")
    finally:
        _disarm()

    assert config.exists()


def test_self_widening_does_not_take_effect_on_the_next_activation(tmp_path: Path) -> None:
    """The exact NA1 repro: a profile exposes its own directory read-write, the
    sandboxed code tries to append a wider rule to the active config, and a
    second activation (a fresh daemon process in production) must still deny
    what the original profile denied."""
    config = tmp_path / ".py-sandboxes"
    config.write_text(f"py-sandbox=true\nexpose-rw={tmp_path}\nos-sandbox=none\nlearn=false\n")
    outside = tmp_path.parent / "na1_outside_canary.txt"
    outside.write_text("untouched\n")
    try:
        _activate(config)
        try:
            # Negative control: writing outside the exposed directory is already denied.
            with pytest.raises(RuleFileNotFoundError):
                outside.write_text("round1 attempt\n")
            # The attack: append a wider rule to the config this very run loaded.
            with pytest.raises(RulePermissionError):
                with open(config, "a") as f:
                    f.write(f"\nexpose-rw={tmp_path.parent}\n")
        finally:
            _disarm()

        assert config.read_text().count("expose-rw=") == 1

        _activate(config)
        try:
            with pytest.raises(RuleFileNotFoundError):
                outside.write_text("round2 PWNED\n")
        finally:
            _disarm()

        assert outside.read_text() == "untouched\n"
    finally:
        outside.unlink(missing_ok=True)


def test_included_file_is_protected_too(tmp_path: Path) -> None:
    included = tmp_path / "extra.profile"
    included.write_text("env=DUMMY=1\n")
    config = tmp_path / ".py-sandboxes"
    config.write_text(f'py-sandbox=true\nexpose-rw={tmp_path}\nos-sandbox=none\nlearn=false\ninclude "extra.profile"\n')

    _activate(config)
    try:
        with pytest.raises(RulePermissionError):
            open(included, "a").close()
    finally:
        _disarm()


def test_read_only_access_to_the_active_config_still_works(tmp_path: Path) -> None:
    """The protection is write-only: the daemon (and the sandboxed code, since
    the directory is exposed) must still be able to read the file it runs
    under."""
    config = tmp_path / ".py-sandboxes"
    config.write_text(f"py-sandbox=true\nexpose-rw={tmp_path}\nos-sandbox=none\nlearn=false\n")

    _activate(config)
    try:
        assert "expose-rw" in config.read_text()
    finally:
        _disarm()
