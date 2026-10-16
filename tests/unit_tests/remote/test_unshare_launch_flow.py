# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`UnshareSSEDaemon._get_unshare_flags` and `_launch`, with the subprocess, the threads and the HTTP ping faked."""

import asyncio
import errno
import os
import subprocess
import pickle
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from aiohttp import ClientConnectorError, ClientOSError, ServerDisconnectedError

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_socket import parse_rules as parse_socket_rules
from pysandboxes.remote import unshare_sse_daemon as usd
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon
from pysandboxes.sb_types import ConfigLine

_TEMPLATE = ["--net", "--user", "-r", "--mount", "--propagation", "private", "--pid", "--fork", "--kill-child"]


class TestUnshareFlags:
    def test_the_template_flags_come_first_and_in_order(self) -> None:
        flags = UnshareSSEDaemon("tok")._get_unshare_flags(EmptyRules, {})

        assert flags == _TEMPLATE

    def test_the_profile_parameters_follow_the_template(self) -> None:
        rules = EmptyRules._replace(os_sandbox_params={"a": "1", "b": "", "c": "x y"})  # type: ignore[arg-type]

        flags = UnshareSSEDaemon("tok")._get_unshare_flags(rules, {})

        assert flags == [*_TEMPLATE, "--a=1", "--b", "--c=x y"]

    def test_the_caller_environment_receives_the_user_and_group_ids(self) -> None:
        envs: dict[str, str] = {}

        UnshareSSEDaemon("tok")._get_unshare_flags(EmptyRules, envs)

        assert envs == {"UID": str(os.getuid()), "GID": str(os.getgid())}


class _Process:
    pid = 4321


class _Ping:
    """The HTTP session of the readiness ping: each call plays the next outcome, a status or an exception."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.urls: list[str] = []
        self.timeouts: list[Any] = []

    def __call__(self, **kwargs: Any) -> "_Ping":
        self.session_kwargs = kwargs
        return self

    async def __aenter__(self) -> "_Ping":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def get(self, url: str, timeout: Any = None) -> "_Ping":
        self.urls.append(url)
        self.timeouts.append(timeout)
        self.outcome = self.outcomes.pop(0)
        return self

    @property
    def status(self) -> int:
        return self.outcome


def _raising(ping: _Ping) -> Any:
    class _Get:
        async def __aenter__(self) -> Any:
            outcome = ping.outcome
            if isinstance(outcome, BaseException):
                raise outcome
            return ping

        async def __aexit__(self, *exc: Any) -> None:
            return None

    return _Get()


class _Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.threads: list[dict[str, Any]] = []
        self.sleeps: list[float] = []
        self.exec_calls: list[tuple[Any, dict[str, Any]]] = []
        self.logger = Mock()
        self.ping = _Ping(200)
        self.ports = ""
        self.pid_text = ""

    def thread(self, **kwargs: Any) -> Any:
        record = dict(kwargs)
        self.threads.append(record)
        return Mock(start=Mock(side_effect=lambda: record.setdefault("started", True)))

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)

    async def to_thread(self, function: Any, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    async def create_exec(self, *cmd: Any, **kwargs: Any) -> Any:
        self.exec_calls.append((cmd, kwargs))
        return _Process()

    def mkfifo(self, path: Any, *args: Any) -> None:
        Path(path).touch()

    def launch(self, daemon: UnshareSSEDaemon, rules: Any = EmptyRules, **kwargs: Any) -> None:
        ping = self.ping
        fake_get = ping.get

        def get(url: str, timeout: Any = None) -> Any:
            fake_get(url, timeout)
            return _raising(ping)

        ping.get = get  # type: ignore[method-assign]
        params: dict[str, Any] = {"envs": {"K": "v"}, "log_level": 11, "init_fn": None, "first": False}
        params.update(kwargs)

        class _Config:
            def to_json(self) -> str:
                return "{}"

        async def run() -> None:
            with (
                patch.object(UnshareSSEDaemon, "_prepare_unshare_config", lambda *_: (_Config(), [])),
                patch.object(usd.threading, "Thread", self.thread),
                patch.object(usd.asyncio, "sleep", self.sleep),
                patch.object(usd.asyncio, "to_thread", self.to_thread),
                patch.object(usd.asyncio, "create_subprocess_exec", self.create_exec),
                patch.object(usd.os, "mkfifo", self.mkfifo),
                patch.object(usd.aiohttp, "ClientSession", ping),
                patch.object(usd, "slirp_extract_port_forwards", return_value=self.ports),
                patch.object(usd, "pysandboxes_logger", self.logger),
            ):
                await daemon._launch(rules, **params)

        try:
            asyncio.run(asyncio.wait_for(run(), 10))
        finally:
            self._close(daemon)

    def _close(self, daemon: UnshareSSEDaemon) -> None:
        for record in self.threads:
            if record.get("target") is usd.slirp_run_watcher:
                try:
                    os.close(record["args"][1])
                except OSError:
                    pass
        if daemon._slirp_pid_file and Path(daemon._slirp_pid_file).exists():
            self.pid_text = Path(daemon._slirp_pid_file).read_text()
        for value in (daemon._slirp_pid_file, daemon._slirp_api_socket):
            if value:
                Path(value).unlink(missing_ok=True)


@pytest.fixture
def flow(tmp_path: Path) -> _Fixture:
    return _Fixture(tmp_path)


def _daemon(port: int = 7001) -> UnshareSSEDaemon:
    daemon = UnshareSSEDaemon("tok")
    daemon.port = port
    return daemon


class TestLaunchCommand:
    def test_the_command_chains_unshare_setup_and_the_daemon_through_a_named_pipe(self, flow: _Fixture) -> None:
        daemon = _daemon()

        flow.launch(daemon)

        ((cmd, _),) = flow.exec_calls
        assert cmd[0] == "unshare"
        assert list(cmd[1 : 1 + len(_TEMPLATE)]) == _TEMPLATE
        rest = list(cmd[1 + len(_TEMPLATE) :])
        assert rest[:4] == ["--", sys.executable, "-m", "pysandboxes.remote.unshare_setup"]
        assert rest[4].endswith("unshare_config.json")
        assert rest[5] == "--"
        assert rest[6 : 6 + len(daemon._build_daemon_cmd())] == daemon._build_daemon_cmd()
        assert rest[-2] == "--_named-pipe"
        assert Path(rest[-1]).name.startswith("_")

    def test_without_a_python_path_the_project_root_stands_alone(self, flow: _Fixture, monkeypatch: Any) -> None:
        monkeypatch.delenv("PYTHONPATH", raising=False)

        flow.launch(_daemon())

        assert flow.exec_calls[0][1]["env"]["PYTHONPATH"] == os.getcwd()

    def test_the_child_runs_with_a_restrictive_umask(self, flow: _Fixture) -> None:
        flow.launch(_daemon())

        preexec = flow.exec_calls[0][1]["preexec_fn"]
        old = os.umask(0o022)
        try:
            preexec()
            assert os.umask(old) == 0o006
        finally:
            os.umask(old)

    def test_the_read_end_of_the_slirp_pipe_is_closed_in_the_parent(self, flow: _Fixture) -> None:
        flow.launch(_daemon())

        (read_fd,) = flow.exec_calls[0][1]["pass_fds"]
        with pytest.raises(OSError):
            os.fstat(read_fd)


class TestLaunchState:
    def test_the_daemon_is_started_and_accepting_once_the_ping_answers(self, flow: _Fixture) -> None:
        daemon = _daemon()

        flow.launch(daemon)

        assert daemon.is_started is True
        assert daemon._accept_incoming is True
        assert isinstance(daemon._process, _Process)

    def test_the_pid_of_the_process_is_written_for_slirp(self, flow: _Fixture) -> None:
        daemon = _daemon()

        flow.launch(daemon)

        assert flow.pid_text == "4321"

    def test_the_slirp_files_are_remembered_for_the_shutdown(self, flow: _Fixture) -> None:
        daemon = _daemon()

        flow.launch(daemon)

        assert daemon._slirp_pid_file == flow.exec_calls[0][1]["env"]["PID_FILE"]
        assert daemon._slirp_api_socket

    def test_the_chroot_root_is_reserved_for_the_launch(self, flow: _Fixture) -> None:
        daemon = _daemon()
        try:
            flow.launch(daemon)

            assert len(daemon._chroot_dirs) == 1
        finally:
            daemon._remove_chroot_dirs()

    def test_the_first_start_and_a_restart_are_not_logged_alike(self, flow: _Fixture) -> None:
        flow.launch(_daemon(), first=True)
        flow.logger.info.assert_called_once_with("Unshare Daemon Sandbox started")
        flow.logger.warning.assert_not_called()

        flow.logger.reset_mock()
        flow.ping = _Ping(200)
        flow.launch(_daemon(), first=False)
        flow.logger.warning.assert_called_once_with("Unshare Daemon Sandbox re-started")
        flow.logger.info.assert_not_called()


class TestRestartFreesTheForwardedPorts:
    """The slirp4netns of a sandbox that died does not notice: it keeps the host ports the new one forwards."""

    def test_the_slirp_of_the_dead_sandbox_is_killed_before_the_new_one_starts(self, flow: _Fixture) -> None:
        daemon = _daemon()
        previous = Mock()
        daemon._slirp_process_holder[0] = previous
        order: list[str] = []
        previous.kill.side_effect = lambda: order.append("killed")
        previous.wait.side_effect = lambda timeout=None: order.append(f"waited {timeout}")
        original = flow.create_exec

        async def create_exec(*cmd: Any, **kwargs: Any) -> Any:
            order.append("launched")
            return await original(*cmd, **kwargs)

        flow.create_exec = create_exec  # type: ignore[method-assign]

        flow.launch(daemon)

        assert order == ["killed", "waited 5", "launched"]
        assert daemon._slirp_process_holder[0] is None

    def test_a_first_start_has_nothing_to_kill(self) -> None:
        daemon = _daemon()

        daemon._stop_previous_slirp()

        assert daemon._slirp_process_holder == [None]

    def test_a_slirp_already_gone_does_not_stop_the_restart(self) -> None:
        daemon = _daemon()
        previous = Mock()
        previous.kill.side_effect = ProcessLookupError
        daemon._slirp_process_holder[0] = previous

        daemon._stop_previous_slirp()

        assert daemon._slirp_process_holder[0] is None

    def test_a_slirp_that_does_not_die_in_time_is_dropped_all_the_same(self) -> None:
        daemon = _daemon()
        previous = Mock()
        previous.wait.side_effect = subprocess.TimeoutExpired("slirp4netns", 5)
        daemon._slirp_process_holder[0] = previous

        daemon._stop_previous_slirp()

        previous.kill.assert_called_once_with()
        assert daemon._slirp_process_holder[0] is None


class TestLaunchThreads:
    def test_the_slirp_watcher_gets_the_event_the_pipe_the_socket_and_the_holder(self, flow: _Fixture) -> None:
        daemon = _daemon()

        flow.launch(daemon)

        (watcher,) = [t for t in flow.threads if t["target"] is usd.slirp_run_watcher]
        event, pipe_w, api_socket = watcher["args"]
        assert event is daemon._slirp_shutdown_event
        assert api_socket == daemon._slirp_api_socket
        assert watcher["kwargs"] == {
            "pid_file": daemon._slirp_pid_file,
            "process_holder": daemon._slirp_process_holder,
            "timeout": usd.SLIRP_WATCHER_TIMEOUT,
        }
        assert watcher["daemon"] is True and watcher["started"] is True

    def test_the_forwarded_ports_get_their_own_thread(self, flow: _Fixture) -> None:
        flow.ports = "tcp:80"
        daemon = _daemon()

        flow.launch(daemon)

        (forwarding,) = [t for t in flow.threads if t["target"] is usd.slirp_setup_port_forwarding]
        assert forwarding["args"] == (daemon._slirp_api_socket, "tcp:80")
        assert forwarding["daemon"] is True and forwarding["started"] is True

    def test_without_forwarded_ports_there_is_no_forwarding_thread(self, flow: _Fixture) -> None:
        flow.launch(_daemon())

        assert [t for t in flow.threads if t["target"] is usd.slirp_setup_port_forwarding] == []

    def test_the_config_is_published_by_a_daemon_thread(self, flow: _Fixture) -> None:
        flow.launch(_daemon())

        (publisher,) = [t for t in flow.threads if t["target"].__name__ == "publish_config"]
        assert publisher["daemon"] is True and publisher["started"] is True


class TestLaunchParameters:
    def _sent(self, flow: _Fixture, **kwargs: Any) -> Any:
        written: list[bytes] = []
        real_open = open

        def spy(path: Any, mode: str = "r", *args: Any, **kw: Any) -> Any:
            handle = real_open(path, mode, *args, **kw)
            if mode == "wb":
                original = handle.write

                def write(data: bytes) -> int:
                    written.append(data)
                    return original(data)

                handle.write = write  # type: ignore[method-assign,assignment]
            return handle

        with patch("builtins.open", spy):
            flow.launch(_daemon(), **kwargs)
        (data,) = written
        return pickle.loads(data)

    def test_the_sandbox_receives_its_token_port_level_and_open_bind_address(self, flow: _Fixture) -> None:
        params = self._sent(flow)

        assert params.token == "tok"
        assert params.port == 7001
        assert params.log_level == 11
        assert params.bind_host == "0.0.0.0"
        assert params.init_fn == ""

    def test_the_init_function_is_sent_as_a_module_reference(self, flow: _Fixture) -> None:
        params = self._sent(flow, init_fn=os.getcwd)

        assert params.init_fn == "posixpath:getcwd" or params.init_fn.endswith(":getcwd")

    def test_the_port_rule_for_the_daemon_is_added_to_the_socket_rules(self, flow: _Fixture) -> None:
        existing, _, _ = parse_socket_rules([ConfigLine("net=ALLOW|TCP|1.1.1.1|443|OUT", Path(), 0)], [])
        rules = EmptyRules._replace(socket_rules=tuple(existing))  # type: ignore[arg-type]

        params = self._sent(flow, rules=rules)

        sources = [r.config.rule for r in params.all_rules.socket_rules]
        assert sources[0] == "net=ALLOW|TCP|1.1.1.1|443|OUT"
        assert sources[1:] == ["net=ALLOW|TCP|*|7001|IN"] * 2


class TestPing:
    def test_the_ping_targets_the_daemon_port(self, flow: _Fixture) -> None:
        flow.launch(_daemon(7123))

        assert flow.ping.urls == ["http://127.0.0.1:7123/ping"]

    def test_the_session_reads_with_the_sse_buffer_and_the_ping_has_a_timeout(self, flow: _Fixture) -> None:
        flow.launch(_daemon())

        assert flow.ping.session_kwargs == {"read_bufsize": usd.SSE_READ_BUFSIZE}
        assert flow.ping.timeouts[0].total == usd.TIMEOUT_FOR_PING

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
    def test_a_transient_failure_is_retried_after_the_ping_interval(self, flow: _Fixture, failure: Exception) -> None:
        flow.ping = _Ping(failure, 200)

        flow.launch(_daemon())

        assert len(flow.ping.urls) == 2
        assert flow.sleeps == [usd.INTERVAL_FOR_PING_DAEMON, usd.INTERVAL_FOR_PING_DAEMON]

    def test_a_ready_daemon_is_given_one_more_interval(self, flow: _Fixture) -> None:
        flow.launch(_daemon())

        assert flow.sleeps == [usd.INTERVAL_FOR_PING_DAEMON]

    @pytest.mark.parametrize("failure", [ClientOSError("no errno"), ClientOSError(errno.ECONNREFUSED, "refused")])
    def test_an_error_without_a_transient_errno_stops_the_launch(self, flow: _Fixture, failure: Exception) -> None:
        flow.ping = _Ping(failure)
        daemon = _daemon()

        with pytest.raises(ClientOSError):
            flow.launch(daemon)

        assert daemon.is_started is False

    def test_an_unexpected_status_stops_the_launch(self, flow: _Fixture) -> None:
        flow.ping = _Ping(503)

        with pytest.raises(RuntimeError, match=r"Unexpected status 503 from http://127.0.0.1:7001/ping"):
            flow.launch(_daemon())

    @pytest.mark.parametrize("status", [100, 199, 201, 204, 404])
    def test_only_the_status_200_means_ready(self, flow: _Fixture, status: int) -> None:
        flow.ping = _Ping(status)

        with pytest.raises(RuntimeError, match=f"Unexpected status {status} "):
            flow.launch(_daemon())

    def test_the_process_is_started_through_the_sandbox_loop(self, flow: _Fixture) -> None:
        decorated: list[str] = []

        def sandbox_loop(func: Any) -> Any:
            decorated.append(func.__name__)
            return func

        with patch.object(usd, "sandbox_loop", sandbox_loop):
            flow.launch(_daemon())

        assert decorated == ["_do_launch"]

    def test_a_daemon_that_never_answers_ends_in_a_sandbox_error(self, flow: _Fixture) -> None:
        flow.ping = _Ping(*([TimeoutError()] * 3))
        daemon = _daemon()

        with patch.object(usd, "LOOP_FOR_PING", 2), pytest.raises(SandBoxError, match="never answered on http://"):
            flow.launch(daemon)

        assert daemon.is_started is False
        assert len(flow.ping.urls) == 2

    def test_a_failed_launch_leaves_the_daemon_not_accepting(self, flow: _Fixture) -> None:
        flow.ping = _Ping(503)
        daemon = _daemon()
        daemon._accept_incoming = True
        daemon._is_started = True

        with pytest.raises(RuntimeError):
            flow.launch(daemon)

        assert daemon._accept_incoming is False
        assert daemon.is_started is False


class TestDebugLaunch:
    def test_the_command_is_written_to_a_script_in_debug_mode(self, flow: _Fixture, monkeypatch: Any) -> None:
        monkeypatch.chdir(flow.tmp_path)
        with patch.object(usd, "DEBUG_LAUNCH", True):
            flow.launch(_daemon())

        script = (flow.tmp_path / "tmp" / "run.sh").read_text()
        assert script.startswith("#!/bin/bash\nunshare ")
        assert "pysandboxes.remote.unshare_setup" in script
        assert script.endswith("\n")

    def test_the_config_is_a_plain_file_in_debug_mode(self, flow: _Fixture, monkeypatch: Any) -> None:
        monkeypatch.chdir(flow.tmp_path)
        with patch.object(usd, "DEBUG_LAUNCH", True):
            flow.launch(_daemon())

        assert flow.exec_calls[0][0][len(_TEMPLATE) + 5] == str(
            (flow.tmp_path / "tmp" / "unshare_config.json").resolve()
        )

    def test_an_unwritable_script_does_not_stop_the_launch(self, flow: _Fixture, monkeypatch: Any) -> None:
        monkeypatch.chdir(flow.tmp_path)
        real = Path.write_text

        def write_text(path: Path, *args: Any, **kwargs: Any) -> int:
            if path.name == "run.sh":
                raise OSError("ro")
            return real(path, *args, **kwargs)

        with patch.object(usd, "DEBUG_LAUNCH", True), patch.object(Path, "write_text", write_text):
            daemon = _daemon()
            flow.launch(daemon)

        assert not (flow.tmp_path / "tmp" / "run.sh").exists()
        assert daemon.is_started is True
