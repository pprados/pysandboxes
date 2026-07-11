# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A pre-import must claim one module, never everything it dragged along.

In partial mode the sandboxed process becomes the SSE server, and
``run_server()`` imports that server lazily -- after the guards are armed, so
the whole transport stack was charged to the user's ``python-import`` rules.
That is why the partial profile was always the larger of the two, and why every
framework bump invalidated it: it described the transport, not the tools.

``preimport_framework_module`` loads such a module before arming and keeps it
across the eviction. The tempting shortcut is to also keep everything the
import pulled in, which would fix the profiles in one line. It must not be
taken: importing fastapi alone brings ``subprocess``, ``ctypes``, ``_socket``
and ``pickle`` into ``sys.modules``, a module found there never reaches the
import guard again, and the exemption would hand user code exactly the names
the profiles mark ``# Dangerous!``.

These tests pin the narrow behaviour, so the shortcut cannot be introduced
later without a red test.

Pre-importing the transport stack was tried and reverted. It does shrink the
partial profiles -- 31 fewer modules on langchain-demo, measured by emptying
the learned rules and relearning -- but it breaks the error path: the modules
fastapi drags in are already in ``sys.modules`` while learning observes, so
they are never recorded, the eviction then drops them, and a later re-import on
the error path is denied. It cost three integration tests in
``test_exception_crosses_armed_profile.py``. Fixing it properly needs the guard
to separate "resident in sys.modules" from "allowed", which Python's import
machinery does not offer for free.
"""

import sys

from pysandboxes.guard_import import _framework_modules, preimport_framework_module

_DANGEROUS = ("subprocess", "ctypes", "_socket", "pickle")


def test_only_the_named_module_is_registered() -> None:
    """A pre-import claims its own name and nothing else."""
    before = set(_framework_modules)
    try:
        preimport_framework_module("json")
        assert _framework_modules - before == {"json"}
    finally:
        _framework_modules.difference_update({"json"})


def test_the_transitive_imports_are_not_registered() -> None:
    """The dependencies an import pulls in stay the user's to allow.

    ``email.parser`` is a stdlib module that imports several others; none of
    them may end up exempt just for having been on its path.
    """
    before = set(_framework_modules)
    modules_before = set(sys.modules)
    try:
        preimport_framework_module("email.parser")
        pulled = set(sys.modules) - modules_before
        registered = _framework_modules - before
        assert registered == {"email.parser"}
        assert not (pulled & registered - {"email.parser"})
    finally:
        _framework_modules.difference_update({"email.parser"})


def test_no_dangerous_name_is_registered_by_the_transport_preimport() -> None:
    """The names the profiles call dangerous are never claimed as the framework's.

    Read from the source rather than from a live arming: the pre-import runs in
    the sandboxed child, so the parent's ``_framework_modules`` stays empty and
    an assertion against it here would be vacuous.

    Today only ``tblib`` is pre-imported. Widening that to the transport stack
    was measured and reverted -- see the module docstring -- so this guards the
    next attempt rather than the current state.
    """
    from pathlib import Path

    from pysandboxes.remote import main_sandbox

    source = Path(main_sandbox.__file__).read_text()
    for line in source.splitlines():
        if "preimport_framework_module(" not in line or line.lstrip().startswith("#"):
            continue
        for name in _DANGEROUS:
            assert f'"{name}"' not in line, f"{name} must not be pre-imported: {line.strip()}"
