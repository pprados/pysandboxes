# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`BaseSubProcessDaemon`: command, start, restart, readiness ping, watchdog cancellation and shutdown."""

import asyncio
import errno
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import ClientConnectorError, ClientOSError, ServerDisconnectedError

from pysandboxes.all_rules import EmptyRules
from pysandboxes.base_daemon import BaseDaemon
from pysandboxes.e import SandBoxError
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import client_subprocess_sse_daemon as csd
from pysandboxes.remote import main_sandbox, main_shutdown, parameters
from pysandboxes.remote.client_subprocess_sse_daemon import SubProcessDaemon
from pysandboxes.sb_types import Envs


def _sys(level: int) -> Any:
    return SimpleNamespace(executable=sys.executable, flags=SimpleNamespace(optimize=level))


class TestConstruction:
    def test_the_defaults_come_from_the_parameters_module(self) -> None:
        daemon = SubProcessDaemon("tok")

        assert daemon.max_connect_retry == parameters.MAX_CONNECT_RETRY
        assert daemon._max_attempts == parameters.RETRY_MAX_ATTEMPTS
        assert daemon._base_delay == parameters.RETRY_BASE_DELAY
        assert daemon._factor == parameters.RETRY_FACTOR
        assert daemon._max_delay == parameters.RETRY_MAX_DELAY
        assert daemon._reset_delay == parameters.RETRY_RESET_DELAY
        assert daemon._process is None and daemon._watchdog is None
        assert daemon._attempts == 0

    def test_every_setting_is_kept(self) -> None:
        daemon = SubProcessDaemon(
            "tok", max_connect_retry=2, max_attempts=3, base_delay=0.5, factor=4.0, max_delay=9.0, reset_delay=7.0
        )

        assert daemon.max_connect_retry == 2
        assert daemon._max_attempts == 3
        assert daemon._base_delay == 0.5
        assert daemon._factor == 4.0
        assert daemon._max_delay == 9.0
        assert daemon._reset_delay == 7.0


class TestHooks:
    def test_the_default_hooks(self) -> None:
        daemon = SubProcessDaemon("tok")

        assert daemon._ping_url(4321) == "http://127.0.0.1:4321/ping"
        assert daemon._sse_bind_host(["x"]) == "127.0.0.1"
        assert daemon.get_launch_extras() == (None, ())
        daemon.on_process_launched(1)
        assert asyncio.run(daemon._on_process_started()) is None

    def test_a_plain_subprocess_keeps_the_rules_as_they_are(self, tmp_path: Path) -> None:
        daemon = SubProcessDaemon("tok")

        assert daemon.update_rules_and_activate(envs=Envs({}), all_rules=EmptyRules, temp=tmp_path) is EmptyRules


class TestSubprocessCmd:
    def _cmd(self, daemon: SubProcessDaemon, tmp_path: Path, level: int = 0) -> Any:
        with patch.object(csd, "sys", _sys(level)):
            return daemon.subprocess_cmd(EmptyRules, {}, tmp_path / "pipe", tmp_path)

    def test_the_child_runs_main_sandbox_unbuffered_with_no_extra_environment(self, tmp_path: Path) -> None:
        cmd, env = self._cmd(SubProcessDaemon("tok"), tmp_path)

        assert cmd == [sys.executable, "-u", "-m", main_sandbox.__name__]
        assert env == {}

    @pytest.mark.parametrize("level", [1, 2])
    def test_the_optimisation_level_is_forwarded(self, level: int) -> None:
        cmd, _ = self._cmd(SubProcessDaemon("tok", python_args=["-X", "dev"]), Path("."), level)

        assert cmd == [sys.executable, "-u", "-" + "O" * level, "-X", "dev", "-m", main_sandbox.__name__]


class TestStart:
    def _start(self, daemon: SubProcessDaemon, rules: Any) -> tuple[Any, Any, Any]:
        async def run() -> tuple[Any, Any, Any]:
            with (
                patch.object(SubProcessDaemon, "_re_start", AsyncMock()) as restart,
                patch.object(SubProcessDaemon, "watchdog", AsyncMock()) as watchdog,
            ):
                await daemon._start(rules, envs={"A": "b"}, log_level=7, init_fn=None)
                task = daemon._watchdog
                assert task is not None
                await task
                return restart, watchdog, task

        return asyncio.run(run())

    def test_the_first_start_is_marked_and_the_watchdog_follows(self) -> None:
        daemon = SubProcessDaemon("tok")
        daemon.restart = 5

        restart, watchdog, task = self._start(daemon, EmptyRules._replace(port=4321))

        assert daemon.restart == 0
        restart.assert_awaited_once_with(
            EmptyRules._replace(port=4321), envs={"A": "b"}, log_level=7, init_fn=None, first=True
        )
        watchdog.assert_called_once_with(EmptyRules._replace(port=4321), envs={"A": "b"}, log_level=7, init_fn=None)
        assert task.get_name() == "ControlDaemon"

    @pytest.mark.parametrize("port", [0, -2])
    def test_a_port_fixed_by_the_rules_is_kept(self, port: int) -> None:
        daemon = SubProcessDaemon("tok")

        self._start(daemon, EmptyRules._replace(port=port))

        assert daemon.port == port


class TestRestart:
    def _restart(self, daemon: SubProcessDaemon, *, first: bool, rules: Any = EmptyRules) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        logger = Mock()

        def subprocess_cmd(self: Any, **kwargs: Any) -> Any:
            seen["cmd_kwargs"] = kwargs
            seen["temp_exists"] = kwargs["temp"].is_dir()
            return ["cmd"], {"X": "1"}

        async def restart_cmd(self: Any, *args: Any, **kwargs: Any) -> None:
            seen["restart_args"] = args
            seen["restart_kwargs"] = kwargs

        async def run() -> None:
            with (
                patch.object(SubProcessDaemon, "subprocess_cmd", subprocess_cmd),
                patch.object(SubProcessDaemon, "_re_start_cmd", restart_cmd),
                patch.object(csd, "pysandboxes_logger", logger),
            ):
                await daemon._re_start(rules, envs={"E": "v"}, log_level=9, init_fn=print, first=first)

        asyncio.run(run())
        seen["logger"] = logger
        return seen

    def test_the_command_is_built_in_a_private_directory_that_is_removed_afterwards(self) -> None:
        daemon = SubProcessDaemon("tok")
        daemon.port = 7001

        seen = self._restart(daemon, first=True)

        kwargs = seen["cmd_kwargs"]
        assert kwargs["envs"] == {"E": "v"}
        assert kwargs["pipe_path"].parent == kwargs["temp"]
        assert kwargs["pipe_path"].name.startswith("_")
        assert seen["temp_exists"] is True
        assert not kwargs["temp"].exists()

    def test_the_daemon_port_is_opened_in_the_rules_given_to_the_sandbox(self) -> None:
        daemon = SubProcessDaemon("tok")
        daemon.port = 7001

        seen = self._restart(daemon, first=True)

        sources = [r.config.rule for r in seen["cmd_kwargs"]["all_rules"].socket_rules]
        assert sources == ["net=ALLOW|TCP|*|7001|IN"] * 2

    def test_the_restart_receives_the_command_the_environment_the_port_and_the_init_function(self) -> None:
        daemon = SubProcessDaemon("tok")
        daemon.port = 7001

        seen = self._restart(daemon, first=True)

        all_rules, cmds, env = seen["restart_args"]
        assert all_rules is seen["cmd_kwargs"]["all_rules"]
        assert cmds == ["cmd"] and env == {"X": "1"}
        assert seen["restart_kwargs"] == {
            "pipe_path": seen["cmd_kwargs"]["pipe_path"],
            "port": 7001,
            "log_level": 9,
            "init_fn": print,
        }

    def test_a_first_start_and_a_restart_are_not_logged_alike(self) -> None:
        first = self._restart(SubProcessDaemon("tok"), first=True)["logger"]
        again = self._restart(SubProcessDaemon("tok"), first=False)["logger"]

        first.info.assert_called_once_with("Daemon Sandbox started")
        first.warning.assert_not_called()
        again.warning.assert_called_once_with("Daemon Sandbox re-started")
        again.info.assert_not_called()


class _Reply:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    async def __aenter__(self) -> "_Reply":
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    @property
    def status(self) -> int:
        return self.outcome  # type: ignore[no-any-return]


class _Ping:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.urls: list[str] = []
        self.timeouts: list[Any] = []
        self.session_kwargs: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> "_Ping":
        self.session_kwargs = kwargs
        return self

    async def __aenter__(self) -> "_Ping":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def get(self, url: str, timeout: Any = None) -> _Reply:
        self.urls.append(url)
        self.timeouts.append(timeout)
        return _Reply(self.outcomes.pop(0))


class _Child:
    pid = 3131


class _Restart:
    def __init__(self) -> None:
        self.launches: list[tuple[Any, dict[str, Any]]] = []
        self.states: list[tuple[bool, bool]] = []
        self.sleeps: list[float] = []
        self.ping = _Ping(200)
        self.events: list[str] = []

    def run(self, daemon: SubProcessDaemon, rules: Any = EmptyRules, **kwargs: Any) -> None:
        async def launch(args: Any, **kw: Any) -> Any:
            self.events.append("launch")
            self.launches.append((args, kw))
            self.states.append((daemon._is_started, daemon._accept_incoming))
            return _Child()

        async def sleep(delay: float) -> None:
            self.sleeps.append(delay)

        params: dict[str, Any] = {
            "args": ["prog", "a b"],
            "extra_envs": {},
            "pipe_path": Path("/run/pipe"),
            "port": 7001,
            "log_level": 11,
            "init_fn": None,
        }
        params.update(kwargs)

        async def run() -> None:
            with (
                patch.object(csd, "launch_sandbox", launch),
                patch.object(csd.asyncio, "sleep", sleep),
                patch.object(csd.aiohttp, "ClientSession", self.ping),
                patch.object(csd.aiohttp, "TCPConnector", lambda **kw: ("connector", kw)),
                patch.object(csd, "get_log_formatter", return_value="FMT"),
                patch.object(csd, "use_rich_handler", return_value=True),
            ):
                await daemon._re_start_cmd(
                    rules,
                    params.pop("args"),
                    params.pop("extra_envs"),
                    params.pop("pipe_path"),
                    params.pop("port"),
                    log_level=params.pop("log_level"),
                    init_fn=params.pop("init_fn"),
                )

        asyncio.run(asyncio.wait_for(run(), 10))


@pytest.fixture
def restart() -> _Restart:
    return _Restart()


class TestRestartCmd:
    def test_the_launch_gets_the_pipe_argument_and_the_daemon_parameters(self, restart: _Restart) -> None:
        daemon = SubProcessDaemon("secret")

        restart.run(daemon, init_fn=os.getcwd)

        ((args, kwargs),) = restart.launches
        assert args == ["prog", "a b", "--_named-pipe", str(Path("/run/pipe"))]
        assert kwargs["pipe_path"] == Path("/run/pipe")
        config = kwargs["process_config"]
        assert config.token == "secret"
        assert config.port == 7001
        assert config.log_level == 11
        assert config.log_format == "FMT"
        assert config.use_rich_handler is True
        assert config.bind_host == "127.0.0.1"
        assert config.init_fn.endswith(":getcwd")

    def test_without_an_init_function_the_reference_is_empty(self, restart: _Restart) -> None:
        restart.run(SubProcessDaemon("tok"))

        assert restart.launches[0][1]["process_config"].init_fn == ""

    def test_the_bind_host_comes_from_the_hook_with_the_command(self, restart: _Restart) -> None:
        with patch.object(SubProcessDaemon, "_sse_bind_host", lambda self, args: f"host-of-{args[0]}"):
            restart.run(SubProcessDaemon("tok"))

        assert restart.launches[0][1]["process_config"].bind_host == "host-of-prog"

    def test_the_daemon_is_neither_started_nor_accepting_while_it_launches(self, restart: _Restart) -> None:
        daemon = SubProcessDaemon("tok")
        daemon._is_started = True
        daemon._accept_incoming = True

        restart.run(daemon)

        assert restart.states == [(False, False)]

    def test_the_sandbox_environment_is_the_allowed_one_plus_the_extras(self, restart: _Restart) -> None:
        rules = EmptyRules._replace(envs=Envs({"A": "1", "B": "2"}))

        restart.run(SubProcessDaemon("tok"), rules, extra_envs={"B": "x", "C": "3"})

        assert restart.launches[0][1]["envs"] == {"A": "1", "B": "x", "C": "3"}

    def test_learning_adds_the_host_environment_below_the_allowed_one(
        self, restart: _Restart, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PYSB_HOST_ONLY", "host")
        monkeypatch.setenv("PYSB_BOTH", "host")
        rules = EmptyRules._replace(learn=True, envs=Envs({"PYSB_BOTH": "rule"}))

        restart.run(SubProcessDaemon("tok"), rules, extra_envs={"PYSB_EXTRA": "e"})

        env = restart.launches[0][1]["envs"]
        assert env["PYSB_HOST_ONLY"] == "host"
        assert env["PYSB_BOTH"] == "rule"
        assert env["PYSB_EXTRA"] == "e"

    def test_without_learning_the_host_environment_stays_out(
        self, restart: _Restart, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PYSB_HOST_ONLY", "host")

        restart.run(SubProcessDaemon("tok"))

        assert "PYSB_HOST_ONLY" not in restart.launches[0][1]["envs"]

    def test_the_process_is_kept_and_the_start_hook_runs_before_the_ping(self, restart: _Restart) -> None:
        daemon = SubProcessDaemon("tok")

        async def hook(self: Any) -> None:
            restart.events.append("hook")

        with patch.object(SubProcessDaemon, "_on_process_started", hook):
            restart.run(daemon)

        assert isinstance(daemon._process, _Child)
        assert restart.events == ["launch", "hook"]

    def test_a_failing_start_hook_stops_the_start(self, restart: _Restart) -> None:
        daemon = SubProcessDaemon("tok")

        with patch.object(SubProcessDaemon, "_on_process_started", AsyncMock(side_effect=ValueError("hook"))):
            with pytest.raises(ValueError, match="hook"):
                restart.run(daemon)

        assert restart.ping.urls == []
        assert daemon.is_started is False


class TestReadinessPing:
    def test_the_daemon_is_started_and_accepting_once_the_ping_answers(self, restart: _Restart) -> None:
        daemon = SubProcessDaemon("tok")

        restart.run(daemon)

        assert daemon.is_started is True and daemon._accept_incoming is True

    def test_the_ping_asks_the_hook_for_the_url_and_has_a_timeout(self, restart: _Restart) -> None:
        with patch.object(SubProcessDaemon, "_ping_url", lambda self, port: f"http://ping/{port}"):
            restart.run(SubProcessDaemon("tok"), port=7123)

        assert restart.ping.urls == ["http://ping/7123"]
        assert restart.ping.timeouts[0].total == csd.TIMEOUT_FOR_PING

    def test_the_session_uses_an_ipv4_connector_and_the_sse_buffer(self, restart: _Restart) -> None:
        restart.run(SubProcessDaemon("tok"))

        connector, kwargs = restart.ping.session_kwargs["connector"]
        assert connector == "connector" and kwargs == {"family": socket.AF_INET}
        assert restart.ping.session_kwargs["read_bufsize"] == csd.SSE_READ_BUFSIZE

    def test_a_ready_daemon_is_given_one_more_interval(self, restart: _Restart) -> None:
        restart.run(SubProcessDaemon("tok"))

        assert restart.sleeps == [csd.INTERVAL_FOR_PING_DAEMON]

    @pytest.mark.parametrize(
        "failure",
        [
            TimeoutError(),
            ServerDisconnectedError(),
            ClientConnectorError(Mock(), OSError()),
            ClientOSError(errno.ECONNRESET, "reset"),
            ClientOSError(errno.ECONNABORTED, "aborted"),
            ClientOSError(errno.EPIPE, "pipe"),
        ],
    )
    def test_a_transient_failure_is_retried_after_the_ping_interval(
        self, restart: _Restart, failure: Exception
    ) -> None:
        restart.ping = _Ping(failure, 200)

        restart.run(SubProcessDaemon("tok"))

        assert len(restart.ping.urls) == 2
        assert restart.sleeps == [csd.INTERVAL_FOR_PING_DAEMON] * 2

    @pytest.mark.parametrize("failure", [ClientOSError("no errno"), ClientOSError(errno.ECONNREFUSED, "refused")])
    def test_an_error_without_a_transient_errno_stops_the_start(self, restart: _Restart, failure: Exception) -> None:
        restart.ping = _Ping(failure)
        daemon = SubProcessDaemon("tok")

        with pytest.raises(ClientOSError):
            restart.run(daemon)

        assert daemon.is_started is False and daemon._accept_incoming is False

    @pytest.mark.parametrize("status", [100, 199, 201, 404, 503])
    def test_only_the_status_200_means_ready(self, restart: _Restart, status: int) -> None:
        restart.ping = _Ping(status)

        with pytest.raises(RuntimeError, match=f"Unexpected status {status} from http://127.0.0.1:7001/ping"):
            restart.run(SubProcessDaemon("tok"))

    def test_a_daemon_that_never_answers_ends_in_a_sandbox_error(self, restart: _Restart) -> None:
        restart.ping = _Ping(*([TimeoutError()] * 3))
        daemon = SubProcessDaemon("tok")

        with patch.object(csd, "LOOP_FOR_PING", 2), pytest.raises(SandBoxError, match="never answered on http://"):
            restart.run(daemon)

        assert len(restart.ping.urls) == 2
        assert daemon.is_started is False


class TestCancelWatchdog:
    def test_without_a_watchdog_nothing_happens(self) -> None:
        asyncio.run(SubProcessDaemon("tok")._cancel_watchdog())

    def test_a_running_watchdog_is_cancelled_and_forgotten(self) -> None:
        daemon = SubProcessDaemon("tok")

        async def scenario() -> Any:
            task = asyncio.create_task(asyncio.Event().wait())
            daemon._watchdog = task
            await asyncio.sleep(0)
            await daemon._cancel_watchdog()
            return task

        task = asyncio.run(scenario())

        assert task.cancelled() and daemon._watchdog is None

    def test_a_finished_watchdog_is_drained_not_cancelled(self) -> None:
        daemon = SubProcessDaemon("tok")

        async def scenario() -> Any:
            async def done() -> str:
                return "finished"

            task = asyncio.create_task(done())
            daemon._watchdog = task
            await asyncio.sleep(0)
            await daemon._cancel_watchdog()
            return task

        task = asyncio.run(scenario())

        assert not task.cancelled() and task.result() == "finished" and daemon._watchdog is None

    def test_a_watchdog_that_failed_raises_its_error_and_is_still_forgotten(self) -> None:
        daemon = SubProcessDaemon("tok")

        async def scenario() -> None:
            async def failing() -> None:
                raise ValueError("watchdog broke")

            daemon._watchdog = asyncio.create_task(failing())
            await asyncio.sleep(0)
            await daemon._cancel_watchdog()

        with pytest.raises(ValueError, match="watchdog broke"):
            asyncio.run(scenario())

        assert daemon._watchdog is None

    def test_stop_cancels_the_watchdog(self) -> None:
        daemon = SubProcessDaemon("tok")

        with patch.object(SubProcessDaemon, "_cancel_watchdog", AsyncMock()) as cancel:
            asyncio.run(daemon._stop(3))

        cancel.assert_awaited_once_with()


class _Proc:
    def __init__(self, wait: Any = None) -> None:
        self.killed = 0
        self.wait_calls = 0
        self._wait = wait

    async def wait(self) -> int:
        self.wait_calls += 1
        if self._wait is not None:
            return await self._wait()  # type: ignore[no-any-return]
        return 0

    def kill(self) -> None:
        self.killed += 1


class TestShutdown:
    def _shutdown(self, daemon: SubProcessDaemon, graceful: bool = True, call: Any = None) -> Any:
        events: list[str] = []
        call = call or AsyncMock()

        async def cancel(self: Any) -> None:
            events.append(f"cancel:accepting={daemon._accept_incoming}")

        async def parent(self: Any, graceful_shutdown: bool) -> None:
            events.append(f"parent:{graceful_shutdown}")

        async def run() -> None:
            with (
                patch.object(SubProcessDaemon, "_cancel_watchdog", cancel),
                patch.object(BaseDaemon, "_shutdown", parent),
                patch.object(SubProcessDaemon, "async_call_in_sandbox", call),
            ):
                await daemon._shutdown(graceful)

        try:
            asyncio.run(asyncio.wait_for(run(), 10))
        finally:
            self.events, self.call = events, call

    def _daemon(self, process: Any = None, started: bool = True) -> SubProcessDaemon:
        daemon = SubProcessDaemon("tok")
        daemon._process = process if process is not None else _Proc()  # type: ignore[assignment]
        daemon._is_started = started
        daemon._accept_incoming = True
        return daemon

    def test_the_daemon_stops_accepting_then_cancels_the_watchdog_then_runs_the_parent_shutdown(self) -> None:
        daemon = self._daemon()

        self._shutdown(daemon, graceful=False)

        assert self.events == ["cancel:accepting=False", "parent:False"]

    def test_the_remote_shutdown_is_asked_once_with_the_graceful_flag(self) -> None:
        daemon = self._daemon()

        self._shutdown(daemon, graceful=True)

        self.call.assert_awaited_once_with(main_shutdown.daemon_shutdown, True, True)
        assert daemon.max_connect_retry == 1

    def test_the_remote_call_is_bounded_by_the_stop_timeout(self) -> None:
        daemon = self._daemon()
        timeouts: list[float | None] = []
        real = asyncio.wait_for

        async def spy(aw: Any, timeout: float | None = None) -> Any:
            timeouts.append(timeout)
            return await real(aw, timeout)

        with patch.object(csd.asyncio, "wait_for", spy):
            self._shutdown(daemon, graceful=True)

        assert timeouts[1:] == [csd.TIMEOUT_FOR_STOP_DAEMON, csd.TIMEOUT_FOR_STOP_DAEMON]

    def test_a_daemon_that_never_started_is_not_asked_to_shut_down(self) -> None:
        daemon = self._daemon(started=False)

        self._shutdown(daemon)

        self.call.assert_not_awaited()

    def test_a_graceful_shutdown_waits_for_the_process_and_forgets_it(self) -> None:
        process = _Proc()
        daemon = self._daemon(process)

        self._shutdown(daemon, graceful=True)

        assert process.wait_calls == 1 and process.killed == 0
        assert daemon._process is None and daemon.is_started is False

    def test_a_process_that_will_not_exit_is_killed(self) -> None:
        async def never() -> int:
            await asyncio.sleep(30)
            return 0

        process = _Proc(wait=never)
        daemon = self._daemon(process)

        with patch.object(csd, "TIMEOUT_FOR_STOP_DAEMON", 0.05):
            self._shutdown(daemon, graceful=True)

        assert process.killed == 1 and daemon._process is None

    def test_a_remote_shutdown_that_does_not_answer_still_ends_in_the_kill(self) -> None:
        async def hang(*args: Any) -> None:
            await asyncio.sleep(30)

        process = _Proc()
        daemon = self._daemon(process)

        with patch.object(csd, "TIMEOUT_FOR_STOP_DAEMON", 0.05):
            self._shutdown(daemon, graceful=False, call=hang)

        assert process.killed == 1 and daemon._process is None

    def test_a_forced_shutdown_kills_without_waiting(self) -> None:
        process = _Proc()
        daemon = self._daemon(process)

        self._shutdown(daemon, graceful=False)

        assert process.killed == 1 and process.wait_calls == 0

    @pytest.mark.parametrize("error", [OSError("gone"), RuntimeError("loop closed")])
    def test_an_os_or_runtime_error_is_ignored_and_the_state_is_reset(self, error: Exception) -> None:
        daemon = self._daemon()

        self._shutdown(daemon, call=AsyncMock(side_effect=error))

        assert daemon._process is None and daemon.is_started is False

    @pytest.mark.parametrize("error", [SystemExit(3), KeyboardInterrupt()])
    def test_an_exit_request_is_not_swallowed_and_the_state_is_still_reset(self, error: BaseException) -> None:
        daemon = self._daemon()

        with pytest.raises(type(error)):
            self._shutdown(daemon, call=AsyncMock(side_effect=error))

        assert daemon._process is None and daemon.is_started is False

    def test_an_unknown_error_is_reported_and_the_state_is_reset(self) -> None:
        daemon = self._daemon()

        with pytest.raises(AssertionError, match="Unknown error in _shutdown boom"):
            self._shutdown(daemon, call=AsyncMock(side_effect=ValueError("boom")))

        assert daemon._process is None and daemon.is_started is False

    def test_a_shutdown_without_a_process_is_harmless(self) -> None:
        daemon = SubProcessDaemon("tok")
        daemon._is_started = True

        self._shutdown(daemon)

        assert daemon.is_started is False


def test_the_environment_mapping_type_is_not_mutated_by_the_launch() -> None:
    rules = EmptyRules._replace(envs=Envs({"A": "1"}))
    restart = _Restart()

    restart.run(SubProcessDaemon("tok"), rules, extra_envs={"B": "2"})

    assert dict(rules.envs) == {"A": "1"}
    assert isinstance(rules.os_sandbox_params, ImmutableDict)
