# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Guard exceptions must survive the pickle round-trip used by the SSE transport.

A denial raised inside the sandbox is pickled by the sandbox daemon and
unpickled by the caller. An exception whose ``args`` do not match its
constructor arity is lost in transit: the caller receives no result at all and
ends on a timeout, which hides the refusal instead of reporting it.
"""

import pickle

import pytest

from pysandboxes.e import (
    ConfigSyntaxError,
    RuleApiPermissionError,
    RuleFileNotFoundError,
    RuleModuleNotFoundError,
    RulePermissionError,
    RuleSocketConnectionRefusedError,
    SandBoxError,
    SandBoxProtocolError,
)


def test_api_permission_error_round_trip() -> None:
    original = RuleApiPermissionError("subprocess.Popen", "process-exec")
    restored = pickle.loads(pickle.dumps(original))

    assert type(restored) is RuleApiPermissionError
    assert restored.qualname == "subprocess.Popen"
    assert restored.category == "process-exec"
    assert str(restored) == str(original)


def test_config_syntax_error_round_trip() -> None:
    original = ConfigSyntaxError("Syntax error in config files.", ["line 1", "line 2"])
    restored = pickle.loads(pickle.dumps(original))

    assert type(restored) is ConfigSyntaxError
    assert restored.message == original.message
    assert restored.errors == original.errors
    assert str(restored) == str(original)


@pytest.mark.parametrize(
    "exception_class",
    [
        SandBoxError,
        RuleFileNotFoundError,
        RulePermissionError,
        RuleSocketConnectionRefusedError,
        RuleModuleNotFoundError,
    ],
)
def test_message_only_errors_round_trip(exception_class: type[BaseException]) -> None:
    original = exception_class("denied by rule")
    restored = pickle.loads(pickle.dumps(original))

    assert type(restored) is exception_class
    assert str(restored) == str(original)


def test_a_protocol_failure_is_not_an_application_error() -> None:
    """`except SandBoxProtocolError` must never catch what the sandboxed code raised."""
    assert not isinstance(SandBoxError("raised by the application"), SandBoxProtocolError)
    assert not isinstance(RuntimeError("raised by the application"), SandBoxProtocolError)

    # The reverse direction stays usable: the framework's base class still
    # catches both kinds, for a caller that does not care which happened.
    assert isinstance(SandBoxProtocolError("no answer"), SandBoxError)


def test_protocol_error_round_trip() -> None:
    original = SandBoxProtocolError("No result received from the sandbox")
    restored = pickle.loads(pickle.dumps(original))

    assert type(restored) is SandBoxProtocolError
    assert str(restored) == str(original)
