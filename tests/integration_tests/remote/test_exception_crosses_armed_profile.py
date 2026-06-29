# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""An exception raised in the sandbox must reach the caller under an armed profile.

The transport pickles the exception together with a ``tblib`` traceback, and
``catch_stdio`` imports ``tblib`` from inside its own ``except`` handler. That
import is charged to the user's ``python-import`` rules like any other, so a
profile produced by learning never carries it: learning only records what the
run actually imported, and a run that raised nothing never reached the handler.

The result is a chicken-and-egg. Under such a profile the handler's own import
is denied, the response never reaches the wire, and the caller waits out the
RPC timeout instead of seeing the exception. Every guard denial is affected,
which is exactly the case a sandbox has to report well.

``test_exceptions.py`` misses this: its ``config_path`` points at a file that
does not exist next to it, so those tests run in learning mode, where the
import guard records instead of denying.
"""

from pathlib import Path

import pytest

from pysandboxes import sandbox_denials, sandboxes
from pysandboxes.e import SandBoxError, SandBoxProtocolError
from tests.integration_tests.sample import (
    connect_outside_the_rules,
    raise_in_sandbox,
    raise_sandbox_error_in_sandbox,
    run_in_sandbox,
)


def _learn_the_happy_path(tmp_path: Path) -> Path:
    """Produce a profile the way a user does: learn a run that raises nothing."""
    learned = tmp_path / "learned.profile"
    bootstrap = tmp_path / "bootstrap.profile"
    bootstrap.write_text("py-sandbox=true\n" "os-sandbox=subprocess\n" f"learn={learned}\n")

    with sandboxes(sandboxes_config=bootstrap):
        assert run_in_sandbox() == 42

    assert learned.exists()
    return learned


def test_an_exception_crosses_a_learned_profile(tmp_path: Path) -> None:
    learned = _learn_the_happy_path(tmp_path)

    with sandboxes(sandboxes_config=learned):
        with pytest.raises(ValueError, match="raised inside the sandbox"):
            raise_in_sandbox()


def test_an_application_sandbox_error_is_not_reported_as_a_protocol_failure(
    tmp_path: Path,
) -> None:
    """The two kinds of failure the transport reports must stay distinguishable.

    A sandboxed function is free to raise the framework's own SandBoxError.
    That is an application error and must reach the caller as itself, never as
    the SandBoxProtocolError the transport uses for a failed exchange.
    """
    learned = _learn_the_happy_path(tmp_path)

    with sandboxes(sandboxes_config=learned):
        with pytest.raises(SandBoxError) as caught:
            raise_sandbox_error_in_sandbox()

    assert not isinstance(caught.value, SandBoxProtocolError)
    assert "raised by the application" in str(caught.value)


def test_a_denial_is_readable_even_when_the_message_is_rewritten(
    tmp_path: Path,
) -> None:
    """A caller must be able to tell a refused call from a failure of its own.

    Nothing forces the library between the guard and the caller to keep the
    reason: httpx reports a refused connection as "All connection attempts
    failed" and keeps the refusal only in an ExceptionGroup under __context__,
    which the transport does not carry. Asserting on the message would pass for
    any outage, so the framework reports its own denials instead.
    """
    learned = _learn_the_happy_path(tmp_path)

    with sandboxes(sandboxes_config=learned):
        with pytest.raises(OSError) as caught:
            connect_outside_the_rules()

        denials = sandbox_denials(caught.value)
        assert denials, "the refusal did not reach the caller"
        assert any("DENIED" in denial for denial in denials), denials

        # A call the rules allow reports nothing, so the check above cannot pass
        # by accident on an unrelated failure.
        assert sandbox_denials(ValueError("an ordinary error")) == []
