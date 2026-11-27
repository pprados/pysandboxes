# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Security proof test for the configuration loader (AREA B of the cybedefend audit).

Marked run:    pytest tests/unit_tests/security_proofs/test_security_config_include_escalation.py
Raw run:       pytest --runxfail tests/unit_tests/security_proofs/test_security_config_include_escalation.py

``pysandboxes/py_sandbox.py::_parse_include`` only adds a file to ``includes`` (and, through
``parse_config``, to ``AllRules.config_files``) when the included file *exists* at parse time.
``guard_files.set_protected_config_paths`` -- the one thing standing between sandboxed code and a
rewrite of the rules it runs under (NA1, see ``tests/unit_tests/guard/test_guard_files_config_protection.py``)
-- is only ever told about ``config_files``. A profile that names an include which does not exist
yet therefore leaves that exact path unprotected: sandboxed code that holds no more than an
ordinary ``expose-rw`` over its directory can create it, and the next time the same long-lived
profile is loaded (the normal way an application reuses one ``.py-sandboxes`` file across many
``with sandboxes():`` calls, or across restarts), the planted file is read as part of the
profile -- with no review, no approval, and no distinction from a rule the operator wrote.
"""

import importlib
from pathlib import Path
from typing import Any, Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes import guard_api, guard_envs, guard_eval, guard_files, guard_import, guard_socket
from pysandboxes.lifecycle import _reset_for_tests, arm
from pysandboxes.py_sandbox import activate_sandboxes, load_and_parse_config
from pysandboxes.tools import set_is_in_sandbox


@pytest.fixture(autouse=True)
def _restore_patched_functions() -> Iterator[None]:
    """``activate_sandboxes`` patches the stdlib for good; later tests expect the originals."""
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
    """Reload the profile from disk and arm the guards, like a real daemon does on every activation."""
    _reset_for_tests()
    all_rules = load_and_parse_config(config_path=config_path)
    activate_sandboxes(all_rules, rules_provider="none")
    set_is_in_sandbox(True)
    arm()


def _disarm() -> None:
    set_is_in_sandbox(False)
    _reset_for_tests()


def test_security_sandboxed_code_cannot_plant_rules_through_a_missing_include(tmp_path: Path) -> None:
    """A missing ``include`` target must be protected exactly like one that already exists.

    The profile below keeps a strong OS boundary (``os-sandbox=landlock``) and names an
    ``include`` that does not exist yet, in a directory the profile itself exposes read-write
    (a directory the sandboxed code legitimately needs for its own output -- not a mistake by
    the operator). ``test_guard_files_config_protection.py::test_included_file_is_protected_too``
    proves an *existing* include is protected the same way the active profile is; this is the
    other half of that guarantee.
    """
    config = tmp_path / ".py-sandboxes"
    config.write_text(f'py-sandbox=true\nexpose-rw={tmp_path}\nos-sandbox=none\nlearn=false\ninclude "extra.profile"\n')
    planted = tmp_path / "extra.profile"

    _activate(config)
    try:
        # Sandboxed code, writing inside a directory the profile exposes read-write for its own
        # output, plants a line the operator never wrote: a grant to a category denied by
        # default (`guard_api`'s `process-exec`, which covers `os.system`, `subprocess.Popen`...).
        try:
            with open(planted, "w") as f:
                f.write("python-api=ALLOW:process-exec\n")
        except Exception:  # noqa: BLE001 - the guard refusing the write is the expected outcome
            pass
    finally:
        _disarm()

    # The next time the same long-lived profile is loaded -- the ordinary way an application
    # reuses one ``.py-sandboxes`` file -- the planted include must not have silently granted a
    # category of sensitive calls the operator's own profile denies by default.
    reloaded = load_and_parse_config(config_path=config)
    granted_process_exec = any(
        rule.allow and rule.target == "process-exec" and rule.is_category for rule in reloaded.api_rules
    )
    assert not granted_process_exec, (
        f"a file planted by the previous sandboxed run granted api_rules={reloaded.api_rules!r}, "
        "letting the next run call os.system/subprocess.Popen and friends"
    )
