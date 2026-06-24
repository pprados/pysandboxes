# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The `none` provider is a documented no-op, and nothing checked that it stayed one.

`none` is the row of the README guard table that is `❌` everywhere: it exists for
debugging, and it enforces nothing. Two things about it are worth pinning rather
than trusting. It reports `is_in_sandbox()` as true while arming no rule, so code
that branches on that flag behaves as if it were protected when it is not. And it
returns the rule set it is handed untouched, so a mistake that silently routed a
real profile through this daemon would leave every rule unapplied.
"""

import pytest  # type: ignore[import-untyped]

from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote.none_daemon import NoneDaemon
from pysandboxes.tools import is_in_sandbox, set_is_in_sandbox


@pytest.fixture
def daemon() -> NoneDaemon:
    return NoneDaemon("a-token")


@pytest.mark.asyncio
async def test_starting_claims_a_sandbox_without_arming_one(daemon: NoneDaemon) -> None:
    """`is_in_sandbox()` becomes true even though this daemon enforces nothing."""
    assert not is_in_sandbox()
    try:
        await daemon._start(None, envs={}, log_level=0, init_fn=None)  # type: ignore[arg-type]
        assert daemon._is_started
        assert is_in_sandbox(), "the flag is set on purpose, to mimic a real sandbox"
    finally:
        set_is_in_sandbox(False)


@pytest.mark.asyncio
async def test_shutdown_gives_the_flag_back(daemon: NoneDaemon) -> None:
    await daemon._start(None, envs={}, log_level=0, init_fn=None)  # type: ignore[arg-type]
    await daemon._stop(max_pending=0)
    assert is_in_sandbox(), "stop is a no-op here; only shutdown clears the flag"

    await daemon._shutdown()

    assert not is_in_sandbox()
    assert not daemon._is_started


def test_the_rules_come_back_untouched(daemon: NoneDaemon, tmp_path: object) -> None:
    """No rule is applied, and none is dropped either: the same object comes back."""
    sentinel = object()

    result = daemon.update_rules_and_activate(
        envs=ImmutableDict({}),
        all_rules=sentinel,  # type: ignore[arg-type]
        temp=tmp_path,  # type: ignore[arg-type]
    )

    assert result is sentinel


@pytest.mark.asyncio
async def test_it_refuses_to_run_anything_in_a_sandbox(daemon: NoneDaemon) -> None:
    """The three execution paths raise instead of pretending to isolate the call."""
    with pytest.raises(NotImplementedError):
        await daemon.join()
    with pytest.raises(NotImplementedError):
        await daemon.async_call_in_sandbox(lambda: None)
    with pytest.raises(NotImplementedError):
        daemon.call_in_sandbox(lambda: None, False)
