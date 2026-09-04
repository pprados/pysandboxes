# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Single owner of the sandbox lifecycle state.

Two states live here, and conflating them is a bug:

``enter``
    This process *is* the sandboxed child. Learning records instead of
    denying, and the public API tells the inner call from the outer one.

``arm``
    The guards enforce against user code. Deliberately later than the moment
    :func:`pysandboxes.py_sandbox.activate_sandboxes` patches the interpreter:
    framework code runs patched but disarmed, so it needs no exemption and no
    escape hatch. See
    :func:`pysandboxes.guard_import.preimport_framework_module`, which only
    makes sense because arming evicts ``sys.modules``.

Every read of that state goes through this module. Nothing else keeps a copy,
so replacing the backing store (a C extension holding the flag out of reach of
any Python name, or an unremovable :pep:`578` audit hook) touches this file
only.
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

# A counter, not a latch: the SSE daemon enters on top of the process-wide
# enter done by ``main()``, and its shutdown must not report the process as
# out of the sandbox while the guards are still installed and learning still
# has rules to write.
_entered: int = 0
_armed: bool = False


def enter() -> None:
    """Record that this process is the sandboxed child."""
    global _entered
    _entered += 1


def leave() -> None:
    """Undo one :func:`enter`."""
    global _entered
    _entered -= 1
    assert _entered >= 0


def is_in_sandbox() -> bool:
    """Return whether this process is the sandboxed child.

    Independent of enforcement: the ``none`` provider reports ``True`` while
    arming no rule at all, and ``tests/unit_tests/remote/test_none_daemon.py``
    pins that on purpose.
    """
    return _entered > 0


def arm() -> None:
    """Start enforcing, just before user code takes over.

    Idempotent: every entry point may call it. Arming without any guard
    installed is not an error: the ``none`` provider runs user code that way.
    """
    global _armed
    if not _armed:
        logger.debug("lifecycle: armed")
    _armed = True


def is_armed() -> bool:
    """Return whether the guards enforce."""
    return _armed


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _reset_for_tests() -> None:
        """Return the whole framework to its pre-install state.

        The only downgrade path there is, and it does not exist outside a test
        run: defined under the same guard as every ``_deactivate_guard_*`` it
        calls, so production ships no named way to disarm. A backing store that
        Python code cannot write must keep that property.
        """
        global _entered, _armed

        from .guard_api import _deactivate_guard_api
        from .guard_envs import _deactivate_guard_envs
        from .guard_eval import _deactivate_guard_eval
        from .guard_files import _deactivate_guard_files
        from .guard_import import _deactivate_guard_import
        from .guard_socket import _deactivate_guard_sockets

        _deactivate_guard_files()
        _deactivate_guard_sockets()
        _deactivate_guard_import()
        _deactivate_guard_api()
        _deactivate_guard_envs()
        _deactivate_guard_eval()

        _entered = 0
        _armed = False
