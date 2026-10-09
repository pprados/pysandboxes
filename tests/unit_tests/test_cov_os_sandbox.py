# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Lifecycle of the provider singleton in ``_os_sandbox``: registry, refcount, failed starts."""

import asyncio
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes import _os_sandbox
from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.base_daemon import FakeDaemon
from pysandboxes.e import SandBoxError
from pysandboxes.remote.base_sse_daemon import BaseSSESandbox
from pysandboxes.tools import Environ, SyncOrAsyncFunc

_FAKE = "_cov_fake"


class _Process:
    def __init__(self, returncode: int | None, kill_error: Exception | None = None) -> None:
        self.returncode = returncode
        self.kill_error = kill_error
        self.killed = 0

    def kill(self) -> None:
        self.killed += 1
        if self.kill_error:
            raise self.kill_error


class _Daemon(FakeDaemon):
    """A provider whose start can be told to fail, and which records what was asked of it."""

    instances: list["_Daemon"] = []
    start_error: Exception | None = None
    process: _Process | None = None
    start_gate: asyncio.Event | None = None

    def __init__(self, token: str, **kwargs: Any) -> None:
        super().__init__(token, **kwargs)
        self.kwargs = kwargs
        self.shutdowns: list[bool] = []
        self.stops: list[int] = []
        self._process = type(self).process
        type(self).instances.append(self)

    async def _start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        start_gate = type(self).start_gate
        if start_gate is not None:
            await start_gate.wait()
        start_error = type(self).start_error
        if start_error is not None:
            raise start_error
        self._is_started = True
        self._accept_incoming = True

    async def _stop(self, max_pending: int) -> None:
        self.stops.append(max_pending)

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        self.shutdowns.append(graceful_shutdown)
        self._is_started = False


class _Boom(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setitem(_os_sandbox._PROVIDER_SPECS, _FAKE, ("unused", "unused", frozenset({_os_sandbox.sys.platform})))
    monkeypatch.setitem(_os_sandbox._provider_class_cache, _FAKE, _Daemon)
    monkeypatch.setattr(_os_sandbox, "_async_start_lock", asyncio.Lock())
    monkeypatch.setattr(_Daemon, "instances", [])
    monkeypatch.setattr(_Daemon, "start_error", None)
    monkeypatch.setattr(_Daemon, "process", None)
    monkeypatch.setattr(_Daemon, "start_gate", None)
    _os_sandbox._current_daemon = None
    _os_sandbox._startup_counter = 0
    _os_sandbox._starting_daemon = None
    yield
    _os_sandbox._current_daemon = None
    _os_sandbox._startup_counter = 0
    _os_sandbox._starting_daemon = None


def _rules(name: str = _FAKE, **kwargs: Any) -> AllRules:
    return EmptyRules._replace(os_sandbox=name, **kwargs)


async def _start(rules: AllRules | None = None) -> Any:
    return await _os_sandbox.async_start_daemon(rules or _rules(), envs={}, log_level=0, init_fn=None)


def test_the_lazy_factory_lists_the_registry_and_rejects_unknown_names() -> None:
    factory = _os_sandbox.providers_factory

    assert list(factory) == list(_os_sandbox._PROVIDER_SPECS)
    assert len(factory) == len(_os_sandbox._PROVIDER_SPECS)
    assert factory[_FAKE] is _Daemon
    assert 42 not in factory  # type: ignore[comparison-overlap]
    with pytest.raises(KeyError):
        factory["no-such-provider"]


def test_private_providers_are_never_offered() -> None:
    assert _FAKE not in _os_sandbox.platform_providers()


def test_unavailable_reason_comes_from_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_Daemon, "unavailable_reason", classmethod(lambda cls: "no kernel support"))

    assert _os_sandbox.provider_unavailable_reason(_FAKE) == "no kernel support"


def test_the_platform_tag_wins_over_the_provider_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_os_sandbox._PROVIDER_SPECS, _FAKE, ("unused", "unused", frozenset({"no-such-os"})))
    monkeypatch.setattr(_Daemon, "unavailable_reason", classmethod(lambda cls: "probe"))

    reason = _os_sandbox.provider_unavailable_reason(_FAKE)

    assert reason is not None and reason.startswith(f"os-sandbox {_FAKE!r} does not run on")


def test_no_alternative_is_suggested_when_the_platform_has_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_os_sandbox.sys, "platform", "plan9")

    assert _os_sandbox.unsupported_platform_reason("bwrap") == (
        "os-sandbox 'bwrap' does not run on plan9, and no provider does yet"
    )


async def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown daemon name: nope"):
        await _start(_rules("nope"))
    assert _os_sandbox._current_daemon is None


def test_an_unknown_provider_is_refused_by_the_sync_start() -> None:
    with pytest.raises(ValueError, match="Unknown daemon name: nope"):
        _os_sandbox.start_daemon(_rules("nope"), envs={}, log_level=0)


async def test_starts_are_counted_and_only_the_last_shutdown_stops_the_daemon() -> None:
    first = await _start()
    second = await _start()

    assert second is first
    assert len(_Daemon.instances) == 1
    assert _os_sandbox._startup_counter == 2
    assert _os_sandbox.is_daemon_started()
    assert _os_sandbox.is_accept_incoming_call()
    assert _os_sandbox.get_token() == first.token

    await _os_sandbox.async_shutdown_daemon()
    assert first.shutdowns == []
    assert _os_sandbox._current_daemon is first

    await _os_sandbox.async_shutdown_daemon(graceful_shutdown=False)
    assert first.shutdowns == [False]
    assert _os_sandbox._current_daemon is None
    assert not _os_sandbox.is_daemon_started()

    with pytest.raises(ValueError, match="more times than started"):
        await _os_sandbox.async_shutdown_daemon()


async def test_a_refused_extra_shutdown_does_not_corrupt_the_refcount() -> None:
    with pytest.raises(ValueError, match="more times than started"):
        await _os_sandbox.async_shutdown_daemon()

    daemon = await _start()
    await _start()
    await _os_sandbox.async_shutdown_daemon()

    assert daemon.shutdowns == []
    assert _os_sandbox._current_daemon is daemon


async def test_python_args_reach_the_provider() -> None:
    daemon = await _os_sandbox.async_start_daemon(
        _rules(), envs={}, log_level=0, init_fn=None, python_args=["-X", "dev"]
    )

    assert daemon.kwargs == {"python_args": ["-X", "dev"]}


async def test_stop_incoming_call_closes_the_door_and_stop_reaches_the_provider() -> None:
    daemon = await _start()

    await _os_sandbox.stop_incoming_call()
    await _os_sandbox.async_stop_daemon(max_pending=3)

    assert not _os_sandbox.is_accept_incoming_call()
    assert daemon.stops == [3]


async def test_stop_without_a_daemon_does_nothing() -> None:
    await _os_sandbox.stop_incoming_call()
    await _os_sandbox.async_stop_daemon()

    assert _os_sandbox._current_daemon is None
    assert not _os_sandbox.is_accept_incoming_call()


async def test_a_failed_start_kills_the_process_left_behind_and_reraises() -> None:
    _Daemon.start_error = _Boom("no tap device")
    _Daemon.process = _Process(returncode=None)

    with pytest.raises(_Boom, match="no tap device"):
        await _start()

    assert _Daemon.process.killed == 1
    assert _os_sandbox._current_daemon is None
    assert _os_sandbox._starting_daemon is None
    assert _os_sandbox._startup_counter == 0


async def test_a_failed_start_leaves_an_exited_process_alone() -> None:
    _Daemon.start_error = _Boom("exited")
    _Daemon.process = _Process(returncode=1)

    with pytest.raises(_Boom):
        await _start()

    assert _Daemon.process.killed == 0


async def test_a_kill_error_does_not_hide_the_start_failure() -> None:
    _Daemon.start_error = _Boom("the real cause")
    _Daemon.process = _Process(returncode=None, kill_error=ProcessLookupError("gone"))

    with pytest.raises(_Boom, match="the real cause"):
        await _start()

    assert _Daemon.process.killed == 1


class _SSEDaemon(BaseSSESandbox):
    def __init__(self, token: str, **kwargs: Any) -> None:
        super().__init__(token, max_connect_retry=1)

    def update_rules_and_activate(self, *, envs: Any, all_rules: AllRules, temp: Path) -> AllRules:
        return all_rules

    async def _start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        self._is_started = True

    async def _stop(self, max_pending: int) -> None:
        pass

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        self._is_started = False

    def call_in_sandbox(self, func: Callable[..., Any], _force_incomming: bool, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


async def test_the_result_channel_settings_of_the_profile_reach_an_sse_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(_os_sandbox._provider_class_cache, _FAKE, _SSEDaemon)

    daemon = await _start(_rules(remote_result_guard=False, remote_result_data_only=False))

    assert isinstance(daemon, _SSEDaemon)
    assert daemon._result_guard is False
    assert daemon._result_data_only is False


async def test_async_call_in_sandbox_without_a_daemon_is_refused() -> None:
    async def fn() -> int:
        return 1

    with pytest.raises(SandBoxError, match="Daemon not started"):
        await _os_sandbox.async_call_in_sandbox(fn)


def test_call_in_sandbox_without_a_daemon_is_refused() -> None:
    with pytest.raises(SandBoxError, match="Daemon not started"):
        _os_sandbox.call_in_sandbox(len, "abc")


def test_sync_start_and_shutdown_count_the_same_way() -> None:
    first = _os_sandbox.start_daemon(_rules(), envs={}, log_level=0)
    second = _os_sandbox.start_daemon(_rules(), envs={}, log_level=0)

    assert second is first
    assert _os_sandbox._startup_counter == 2

    _os_sandbox.shutdown_daemon()
    assert _os_sandbox._current_daemon is first
    assert first.shutdowns == []

    _os_sandbox.shutdown_daemon()
    assert _os_sandbox._current_daemon is None
    assert first.shutdowns == [True]

    with pytest.raises(ValueError, match="more times than started"):
        _os_sandbox.shutdown_daemon()


def test_a_sync_start_that_times_out_kills_what_it_launched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_os_sandbox, "TIMEOUT_FOR_START_DAEMON", 0.3)
    _Daemon.process = _Process(returncode=None)
    loop = _os_sandbox.get_sandbox_loop()
    gate_ready = threading.Event()

    def _make_gate() -> None:
        _Daemon.start_gate = asyncio.Event()
        gate_ready.set()

    loop.call_soon_threadsafe(_make_gate)
    assert gate_ready.wait(5)
    try:
        with pytest.raises(RuntimeError, match="Daemon failed to start within 0.3s"):
            _os_sandbox.start_daemon(_rules(), envs={}, log_level=0)
        assert _Daemon.process.killed == 1
    finally:
        # Let the pending start finish as a failure, so it never installs a daemon in a later test.
        _Daemon.start_error = _Boom("released")
        released = threading.Event()

        def _release() -> None:
            assert _Daemon.start_gate is not None
            _Daemon.start_gate.set()

        loop.call_soon_threadsafe(_release)

        async def _wait_start_end() -> None:
            while _os_sandbox._starting_daemon is not None:
                await asyncio.sleep(0.01)
            released.set()

        loop.call_soon_threadsafe(lambda: loop.create_task(_wait_start_end()))
        assert released.wait(5)
    assert _os_sandbox._current_daemon is None


def test_a_generated_profile_names_landlock_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_os_sandbox, "unsupported_platform_reason", lambda name: None)
    monkeypatch.setattr(_os_sandbox.providers_factory["landlock"], "unavailable_reason", classmethod(lambda cls: None))

    assert _os_sandbox.default_os_sandbox() == "landlock"


def test_a_generated_profile_names_subprocess_with_a_warning_when_landlock_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(_os_sandbox, "unsupported_platform_reason", lambda name: None)
    monkeypatch.setattr(
        _os_sandbox.providers_factory["landlock"],
        "unavailable_reason",
        classmethod(lambda cls: "no kernel support"),
    )

    with caplog.at_level("WARNING"):
        provider = _os_sandbox.default_os_sandbox()

    assert provider == "subprocess"
    assert "no kernel support" in caplog.text


def test_a_generated_profile_names_subprocess_without_a_warning_on_an_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Non-Linux has no landlock at all: subprocess is expected, not a warning-worthy surprise."""
    monkeypatch.setattr(_os_sandbox, "unsupported_platform_reason", lambda name: f"{name!r} does not run here")

    with caplog.at_level("WARNING"):
        provider = _os_sandbox.default_os_sandbox()

    assert provider == "subprocess"
    assert not caplog.records
