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

from pysandboxes import sandboxes
from tests.integration_tests.sample import raise_in_sandbox, run_in_sandbox


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
