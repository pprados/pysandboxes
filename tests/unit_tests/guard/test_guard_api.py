# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Behaviour of the guard_api layer."""

import pysandboxes
from pysandboxes.e import RuleApiPermissionError, SandBoxError


def test_exception_is_a_permission_error() -> None:
    """User code catching PermissionError keeps working."""
    err = RuleApiPermissionError("os.system", "process-exec")
    assert isinstance(err, PermissionError)
    assert isinstance(err, SandBoxError)


def test_exception_message_tells_how_to_unblock() -> None:
    err = RuleApiPermissionError("os.system", "process-exec")
    message = str(err)
    assert "os.system" in message
    assert "process-exec" in message
    assert "python-api=ALLOW:os.system" in message
    assert "python-api=ALLOW:process-exec" in message


def test_exception_is_exported() -> None:
    assert pysandboxes.RuleApiPermissionError is RuleApiPermissionError
    assert "RuleApiPermissionError" in pysandboxes.__all__


def test_no_dead_name_in_all() -> None:
    """__all__ must not advertise names that do not exist."""
    for name in pysandboxes.__all__:
        assert getattr(pysandboxes, name, None) is not None, name
