# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A daemon that fails to start must say why, and say it at once.

``start_daemon`` and ``shutdown_daemon`` drive their async half as a
task on the sandbox loop and wait on a ``threading.Event``. When that
task raised, nothing set the event: the caller waited out the whole
timeout and then reported "Daemon failed to start within 30s. Check
that unshare/slirp4netns are installed", while the real exception sat
unretrieved in the task. Every startup failure, whatever its cause,
looked like missing sandbox tooling.
"""

import time
from unittest.mock import patch

import pytest  # type: ignore[import-untyped]

from pysandboxes import _os_sandbox
from pysandboxes.all_rules import AllRules
from pysandboxes.py_sandbox import load_and_parse_config


class _Boom(RuntimeError):
    """Distinctive failure raised from inside the daemon start."""


@pytest.fixture
def all_rules(tmp_path) -> AllRules:  # type: ignore[no-untyped-def]
    profile = tmp_path / "start.profile"
    profile.write_text("py-sandbox=true\nos-sandbox=subprocess\npython-import=*\n")
    return load_and_parse_config(config_path=profile)


@pytest.fixture(autouse=True)
def _reset_daemon_state():  # type: ignore[no-untyped-def]
    """Keep the module-level daemon singleton out of other tests."""
    yield
    _os_sandbox._current_daemon = None
    _os_sandbox._startup_counter = 0


def test_start_reports_the_real_exception(all_rules: AllRules) -> None:
    with patch.object(_os_sandbox, "async_start_daemon", side_effect=_Boom("no tap device")):
        with pytest.raises(_Boom, match="no tap device"):
            _os_sandbox.start_daemon(all_rules, envs={}, log_level=0, init_fn=None)


def test_start_failure_does_not_wait_for_the_timeout(all_rules: AllRules) -> None:
    """The event is now set on the failing path, so the wait ends at once."""
    with patch.object(_os_sandbox, "async_start_daemon", side_effect=_Boom("boom")):
        started = time.monotonic()
        with pytest.raises(_Boom):
            _os_sandbox.start_daemon(all_rules, envs={}, log_level=0, init_fn=None)
        elapsed = time.monotonic() - started
    assert elapsed < _os_sandbox.TIMEOUT_FOR_START_DAEMON / 2
