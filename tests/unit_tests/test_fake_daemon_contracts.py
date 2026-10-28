# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import asyncio
from typing import Any

import deal
import pytest  # type: ignore[import-untyped]
from hypothesis import given
from hypothesis import strategies as st

from pysandboxes.base_daemon import FakeDaemon


async def _apply(daemon: FakeDaemon, op: str) -> None:
    if op == "start":
        await daemon._start(None, envs={}, log_level=0, init_fn=None)  # type: ignore[arg-type]
    elif op == "stop":
        await daemon._stop(0)
    elif op == "shutdown":
        await daemon._shutdown(True)
    else:
        await daemon._shutdown()


@given(st.lists(st.sampled_from(["start", "stop", "shutdown", "shutdown-default"]), max_size=12))
def test_a_fake_daemon_is_started_exactly_between_a_start_and_the_next_end(ops: list[str]) -> None:
    daemon = FakeDaemon("token")
    assert not daemon.is_started
    for op in ops:
        asyncio.run(_apply(daemon, op))
        assert daemon.is_started == (op == "start")


def test_the_contracts_are_armed_on_the_fake_daemon_lifecycle() -> None:
    """Negative control: a lifecycle method that forgets to flip the flag is refused by its contract."""
    for name in ("_start", "_stop", "_shutdown"):
        assert hasattr(getattr(FakeDaemon, name), "__deal_contract")

    class Forgetful(FakeDaemon):
        async def _start(self, all_rules: Any, *, envs: Any, log_level: int, init_fn: Any) -> None:
            pass

    wrapped = deal.ensure(lambda self, all_rules, envs, log_level, init_fn, result: self.is_started)(Forgetful._start)
    with pytest.raises(deal.PostContractError):
        asyncio.run(wrapped(Forgetful("t"), None, envs={}, log_level=0, init_fn=None))


@pytest.mark.parametrize("method", ["call_in_sandbox", "async_call_in_sandbox"])
def test_a_fake_daemon_cannot_run_a_function(method: str) -> None:
    daemon = FakeDaemon("token")
    with pytest.raises(NotImplementedError, match="python-sb"):
        result = getattr(daemon, method)(print, False)
        if asyncio.iscoroutine(result):
            asyncio.run(result)


def test_the_token_is_kept_and_a_fresh_daemon_accepts_no_incoming_call() -> None:
    daemon = FakeDaemon("abc")
    assert daemon.token == "abc"
    assert daemon._accept_incoming is False
