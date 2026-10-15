# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`launch_sandbox`, the stream helpers and `find_free_port`, with the subprocess and the terminal faked."""

import asyncio
import os
import pickle
import socket
import stat
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


class _Fed:
    """A stream reader that serves the lines it was given, then EOF."""

    def __init__(self, *lines: bytes) -> None:
        self.lines = list(lines)

    async def readline(self) -> bytes:
        return self.lines.pop(0) if self.lines else b""


class TestReadStream:
    def test_each_line_is_decoded_stripped_and_given_to_the_callback(self) -> None:
        seen: list[str] = []

        asyncio.run(csd._read_stream(_Fed("  héllo \n".encode(), b"two\r\n"), seen.append))  # type: ignore[arg-type]

        assert seen == ["héllo", "two"]

    def test_a_blank_line_does_not_end_the_stream(self) -> None:
        seen: list[str] = []

        asyncio.run(csd._read_stream(_Fed(b"a\n", b"\n", b"b\n"), seen.append))  # type: ignore[arg-type]

        assert seen == ["a", "", "b"]

    def test_the_end_of_the_stream_ends_the_reading(self) -> None:
        seen: list[str] = []

        asyncio.run(csd._read_stream(_Fed(), seen.append))  # type: ignore[arg-type]

        assert seen == []


class _Writer:
    def __init__(self, fail_on: int | None = None) -> None:
        self.data: list[bytes] = []
        self.drained = 0
        self.fail_on = fail_on
        self.failed = False

    def write(self, data: bytes) -> None:
        if self.fail_on is not None and len(self.data) == self.fail_on and not self.failed:
            self.failed = True
            raise BrokenPipeError()
        self.data.append(data)

    async def drain(self) -> None:
        self.drained += 1


class _Stdin:
    def __init__(self, *lines: str) -> None:
        self.lines = list(lines)

    def fileno(self) -> int:
        return 99

    def readline(self) -> str:
        return self.lines.pop(0) if self.lines else ""


class TestWriteStream:
    def _run(self, writer: _Writer, stdin: _Stdin) -> dict[str, Any]:
        record: dict[str, Any] = {"restored": []}
        master, slave = os.pipe()
        record["master"] = master

        with (
            patch("pty.openpty", return_value=(master, slave)),
            patch("termios.tcgetattr", return_value="old-settings"),
            patch("termios.tcsetattr", side_effect=lambda *a: record["restored"].append(a)),
            patch("tty.setraw", side_effect=lambda fd: record.setdefault("raw", fd)),
            patch.object(csd, "sys", SimpleNamespace(stdin=stdin)),
        ):
            asyncio.run(asyncio.wait_for(csd._write_stream(writer), 10))  # type: ignore[arg-type]
        os.close(slave)
        return record

    def test_each_line_is_forwarded_encoded_and_flushed_until_the_end_of_input(self) -> None:
        writer = _Writer()

        self._run(writer, _Stdin("héllo\n", "two\n"))

        assert writer.data == ["héllo\n".encode(), b"two\n"]
        assert writer.drained == 2

    def test_the_terminal_is_made_raw_then_restored_and_the_pty_master_closed(self) -> None:
        record = self._run(_Writer(), _Stdin("a\n"))

        assert record["raw"] == 99
        (restored,) = record["restored"]
        assert restored[0] == 99 and restored[2] == "old-settings"
        with pytest.raises(OSError):
            os.fstat(record["master"])

    def test_a_write_error_ends_the_forwarding_but_still_restores_the_terminal(self) -> None:
        writer = _Writer(fail_on=1)

        record = self._run(writer, _Stdin("a\n", "b\n", "c\n"))

        assert writer.data == [b"a\n"]
        assert len(record["restored"]) == 1


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
