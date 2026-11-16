# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`launch_sandbox`, the stream helpers and `find_free_port`, with the subprocess and the terminal faked."""

import asyncio
import os
import pickle
import socket
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from pysandboxes.remote import client_subprocess_sse_daemon as csd
from pysandboxes.remote.client_subprocess_sse_daemon import find_free_port, launch_sandbox
from pysandboxes.sb_types import Envs


class _Process:
    def __init__(self, pid: int | None = 4242) -> None:
        self.pid = pid
        self.returncode = None


class _Launch:
    """Records the launch: the order of the events, the command and the keyword arguments of the subprocess."""

    def __init__(self, tmp_path: Path, pid: int | None = 4242) -> None:
        self.tmp_path = tmp_path
        self.pid = pid
        self.events: list[str] = []
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.sent = tmp_path / "sent"

    async def create_exec(self, *cmd: Any, **kwargs: Any) -> Any:
        self.events.append("exec")
        self.calls.append((cmd, kwargs))
        return _Process(self.pid)

    async def open_fifo(self, pipe_path: Path, process: Any) -> int:
        self.events.append("fifo")
        assert stat.S_ISFIFO(pipe_path.stat().st_mode)
        return os.open(self.sent, os.O_WRONLY | os.O_CREAT)

    def run(self, config: Any = "config", **kwargs: Any) -> Any:
        async def scenario() -> Any:
            with (
                patch.object(csd.asyncio, "create_subprocess_exec", self.create_exec),
                patch.object(csd, "_open_fifo_for_write", self.open_fifo),
            ):
                return await launch_sandbox(
                    kwargs.pop("cmd", ["prog", "arg"]),
                    kwargs.pop("pipe_path", self.tmp_path / "pipe"),
                    kwargs.pop("envs", Envs({"A": "1"})),
                    config,
                    **kwargs,
                )

        return asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.skipif(sys.platform == "win32", reason="the FIFO launch path and the pty forwarding are POSIX")
class TestLaunchWithFifo:
    def test_the_process_is_returned(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)

        process = launch.run()

        assert isinstance(process, _Process) and process.pid == 4242

    def test_the_command_runs_with_only_the_allowed_environment(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)

        launch.run(envs=Envs({"A": "1", "B": "2"}))

        ((cmd, kwargs),) = launch.calls
        assert cmd == ("prog", "arg")
        assert kwargs["env"] == {"A": "1", "B": "2"}

    def test_the_config_is_pickled_into_the_fifo_which_is_then_removed(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)

        launch.run(config={"k": [1, 2]})

        assert pickle.loads(launch.sent.read_bytes()) == {"k": [1, 2]}
        assert not (tmp_path / "pipe").exists()

    def test_the_caller_hears_of_the_pid_before_the_fifo_is_written(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)
        pids: list[int] = []

        def on_launched(pid: int) -> None:
            launch.events.append("launched")
            pids.append(pid)

        launch.run(on_launched=on_launched)

        assert pids == [4242]
        assert launch.events == ["exec", "launched", "fifo"]

    def test_the_child_umask_is_narrowed_after_the_extra_preexec(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)
        order: list[str] = []
        launch.run(extra_preexec_fn=lambda: order.append(f"extra:{os.umask(0o022):o}"))

        preexec = launch.calls[0][1]["preexec_fn"]
        old = os.umask(0o022)
        try:
            preexec()
            narrowed = os.umask(old)
        finally:
            os.umask(old)
        assert order == ["extra:22"]
        assert narrowed == 0o006

    def test_the_umask_is_narrowed_even_without_an_extra_preexec(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)
        launch.run()

        old = os.umask(0o022)
        try:
            launch.calls[0][1]["preexec_fn"]()
            assert os.umask(old) == 0o006
        finally:
            os.umask(old)

    def test_the_preexec_fn_sets_pdeathsig(self, tmp_path: Path) -> None:
        """The launcher's own crash must not leave the sandbox process running unsupervised."""
        launch = _Launch(tmp_path)
        calls: list[str] = []

        with patch.object(csd, "set_pdeathsig", lambda: calls.append("set")):
            launch.run()
            launch.calls[0][1]["preexec_fn"]()

        assert calls == ["set"]

    def test_optional_arguments_are_passed_only_when_given(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)

        launch.run()

        kwargs = launch.calls[0][1]
        assert set(kwargs) == {"env", "preexec_fn"}

    def test_the_descriptors_and_the_streams_are_passed_when_given(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)

        launch.run(pass_fds=(7, 8), stdout=11, stderr=12, stdin=13)

        kwargs = launch.calls[0][1]
        assert kwargs["pass_fds"] == (7, 8)
        assert (kwargs["stdout"], kwargs["stderr"], kwargs["stdin"]) == (11, 12, 13)

    @pytest.mark.parametrize("name", ["stdout", "stderr", "stdin"])
    def test_a_stream_set_to_zero_is_still_passed(self, tmp_path: Path, name: str) -> None:
        launch = _Launch(tmp_path)

        launch.run(**{name: 0})

        assert launch.calls[0][1][name] == 0


@pytest.mark.skipif(sys.platform == "win32", reason="the FIFO launch path and the pty forwarding are POSIX")
class TestLaunchWithoutFifo:
    def test_a_config_writer_replaces_the_fifo(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)
        written: list[Any] = []

        def writer(config: Any) -> None:
            launch.events.append("writer")
            written.append(config)

        launch.run(config="cfg", config_writer=writer)

        assert written == ["cfg"]
        assert launch.events == ["writer", "exec"]
        assert not (tmp_path / "pipe").exists()

    def test_windows_gets_a_plain_file_and_no_preexec(self, tmp_path: Path) -> None:
        launch = _Launch(tmp_path)

        with patch.object(csd, "sys", SimpleNamespace(platform="".join(["win", "32"]))):
            launch.run(config={"w": 1})

        assert pickle.loads((tmp_path / "pipe").read_bytes()) == {"w": 1}
        assert "preexec_fn" not in launch.calls[0][1]
        assert launch.events == ["exec"]

    @pytest.mark.parametrize("platform", ["linux", "darwin", "freebsd", "zzz-os"])
    def test_every_other_platform_uses_the_fifo_and_the_preexec(self, tmp_path: Path, platform: str) -> None:
        launch = _Launch(tmp_path)

        with patch.object(csd, "sys", SimpleNamespace(platform="".join(list(platform)))):
            launch.run()

        assert launch.events == ["exec", "fifo"]
        assert "preexec_fn" in launch.calls[0][1]


class TestDebugLaunch:
    def test_the_command_is_written_to_a_script(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        launch = _Launch(tmp_path)

        with patch.object(csd, "DEBUG_LAUNCH", True):
            launch.run(cmd=["prog", "a b", "c"])

        script = (tmp_path / "tmp" / "run.sh").read_text()
        assert script == "#!/bin/bash\nprog 'a b' \\\n  c\n"

    def test_the_script_is_written_when_the_debug_directory_already_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tmp").mkdir()

        with patch.object(csd, "DEBUG_LAUNCH", True):
            _Launch(tmp_path).run(cmd=["prog"])

        assert (tmp_path / "tmp" / "run.sh").read_text() == "#!/bin/bash\nprog \n"

    def test_an_unwritable_script_does_not_stop_the_launch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        launch = _Launch(tmp_path)

        with patch.object(csd, "DEBUG_LAUNCH", True), patch.object(Path, "write_text", side_effect=OSError("ro")):
            process = launch.run()

        assert process.pid == 4242

    def test_nothing_is_written_without_the_debug_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)

        _Launch(tmp_path).run()

        assert not (tmp_path / "tmp").exists()


class TestFindFreePort:
    def test_a_bindable_port_is_returned(self) -> None:
        port = find_free_port()

        assert 0 < port < 65536
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))

    def test_the_socket_is_bound_to_any_port_reusable_and_closed(self) -> None:
        events: list[Any] = []

        class _Socket:
            def bind(self, address: Any) -> None:
                events.append(("bind", address))

            def setsockopt(self, *args: Any) -> None:
                events.append(("setsockopt", args))

            def getsockname(self) -> tuple[str, int]:
                return ("0.0.0.0", 5151)

            def close(self) -> None:
                events.append(("close",))

        with patch.object(csd.socket, "socket", lambda *a: _Socket()):
            assert find_free_port() == 5151

        assert events == [
            ("bind", ("", 0)),
            ("setsockopt", (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)),
            ("close",),
        ]

    def test_a_socket_error_is_a_runtime_error_with_its_cause(self) -> None:
        with patch.object(csd.socket, "socket", side_effect=OSError("no sockets")):
            with pytest.raises(RuntimeError, match="Impossible to finding a free port: no sockets") as info:
                find_free_port()

        assert isinstance(info.value.__cause__, OSError)
