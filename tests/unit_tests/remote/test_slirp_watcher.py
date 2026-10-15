# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""slirp4netns port forwarding through its API socket, the pid file wait and the watcher thread."""

import json
import logging
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import slirp4netns_common as slirp


class TestIsSocket:
    def test_a_unix_socket_is_one(self, tmp_path: Path) -> None:
        path = str(tmp_path / "s")
        server = socket.socket(socket.AF_UNIX)
        server.bind(path)
        try:
            assert slirp.is_socket(path) is True
        finally:
            server.close()

    def test_a_regular_file_and_a_directory_are_not(self, tmp_path: Path) -> None:
        file = tmp_path / "f"
        file.write_text("x")

        assert slirp.is_socket(str(file)) is False
        assert slirp.is_socket(str(tmp_path)) is False

    @pytest.mark.parametrize("path", ["/nonexistent/socket", "bad\0path"])
    def test_a_missing_or_invalid_path_is_not(self, path: str) -> None:
        assert slirp.is_socket(path) is False


class _ApiServer:
    """A slirp4netns API stand-in: records every NUL-terminated command and answers with an empty reply."""

    def __init__(self, path: str, fail_first: bool = False) -> None:
        self.path = path
        self.commands: list[dict[str, Any]] = []
        self._fail_first = fail_first
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(path)
        self._server.listen(8)
        self._server.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except (TimeoutError, OSError):
                continue
            with client:
                data = b""
                while not data.endswith(b"\0"):
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                if self._fail_first:
                    self._fail_first = False
                    continue
                self.commands.append(json.loads(data.rstrip(b"\0")))
                client.sendall(b'{"return": {}}')

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2)
        self._server.close()


@pytest.fixture
def api(tmp_path: Path) -> Any:
    servers: list[_ApiServer] = []

    def make(**kwargs: Any) -> _ApiServer:
        server = _ApiServer(str(tmp_path / "api.sock"), **kwargs)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


class TestPortForwarding:
    def test_each_port_is_forwarded_from_the_loopback_to_the_guest(self, api: Any) -> None:
        server = api()

        slirp.setup_port_forwarding(server.path, "tcp:8080 udp:53")

        assert [c["arguments"] for c in server.commands] == [
            {
                "proto": "tcp",
                "host_addr": "127.0.0.1",
                "host_port": 8080,
                "guest_addr": slirp.SLIRP_GUEST_ADDR,
                "guest_port": 8080,
            },
            {
                "proto": "udp",
                "host_addr": "127.0.0.1",
                "host_port": 53,
                "guest_addr": slirp.SLIRP_GUEST_ADDR,
                "guest_port": 53,
            },
        ]
        assert {c["execute"] for c in server.commands} == {"add_hostfwd"}

    def test_nothing_is_done_without_a_port_spec(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(slirp.time, "sleep", lambda delay: pytest.fail("no wait expected"))

        slirp.setup_port_forwarding(str(tmp_path / "absent"), "")

    @pytest.mark.parametrize("spec", ["tcp", "tcp:abc", "tcp:", ":80x"])
    def test_a_malformed_spec_is_skipped_and_the_next_one_is_still_forwarded(self, api: Any, spec: str) -> None:
        server = api()

        slirp.setup_port_forwarding(server.path, f"{spec} tcp:9000")

        assert [c["arguments"]["host_port"] for c in server.commands] == [9000]

    def test_a_refused_forward_does_not_stop_the_other_ones(self, api: Any) -> None:
        server = api(fail_first=True)

        slirp.setup_port_forwarding(server.path, "tcp:1111 tcp:2222")

        assert [c["arguments"]["host_port"] for c in server.commands] == [2222]

    def test_a_socket_that_never_appears_is_reported_after_the_wait(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(slirp.time, "sleep", sleeps.append)

        with caplog.at_level(logging.ERROR, logger=slirp.logger.name):
            slirp.setup_port_forwarding(
                str(tmp_path / "absent"), "tcp:80", socket_wait_attempts=3, socket_wait_interval=0.5
            )

        assert sleeps == [0.5, 0.5, 0.5]
        assert "Port forwarding: API socket not ready" in caplog.text

    def test_a_path_that_is_not_a_socket_is_waited_for_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        plain = tmp_path / "plain"
        plain.write_text("x")
        monkeypatch.setattr(slirp.time, "sleep", lambda delay: None)

        with caplog.at_level(logging.ERROR, logger=slirp.logger.name):
            slirp.setup_port_forwarding(str(plain), "tcp:80", socket_wait_attempts=2)

        assert "API socket not ready" in caplog.text

    def test_the_socket_may_appear_during_the_wait(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = str(tmp_path / "api.sock")
        servers: list[_ApiServer] = []
        sleeps: list[float] = []

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) == 2:
                servers.append(_ApiServer(path))

        monkeypatch.setattr(slirp.time, "sleep", sleep)
        try:
            slirp.setup_port_forwarding(path, "tcp:80", socket_wait_attempts=5, socket_wait_interval=0.01)
            assert sleeps == [0.01, 0.01]
            assert [c["arguments"]["host_port"] for c in servers[0].commands] == [80]
        finally:
            for server in servers:
                server.close()


class TestPidFile:
    def test_the_pid_is_read_once_the_file_has_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pid_file = tmp_path / "pid"
        sleeps: list[float] = []

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) == 2:
                pid_file.write_text(" 4242\n")

        monkeypatch.setattr(slirp.time, "sleep", sleep)

        assert slirp._wait_for_pid_file(str(pid_file), 30, threading.Event()) == 4242
        assert sleeps == [0.05, 0.05]

    def test_a_missing_or_garbage_file_is_waited_on(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pid_file = tmp_path / "pid"
        pid_file.write_text("not a pid")
        calls = [0]

        def sleep(delay: float) -> None:
            calls[0] += 1
            if calls[0] == 3:
                pid_file.write_text("7")

        monkeypatch.setattr(slirp.time, "sleep", sleep)

        assert slirp._wait_for_pid_file(str(pid_file), 30, threading.Event()) == 7

    def test_a_shutdown_gives_no_pid(self, tmp_path: Path) -> None:
        event = threading.Event()
        event.set()
        (tmp_path / "pid").write_text("5")

        assert slirp._wait_for_pid_file(str(tmp_path / "pid"), 30, event) is None

    def test_the_wait_ends_at_the_deadline_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        now = [100.0]
        monkeypatch.setattr(slirp.time, "monotonic", lambda: now[0])
        monkeypatch.setattr(slirp.time, "sleep", lambda delay: now.__setitem__(0, now[0] + 1))

        with caplog.at_level(logging.ERROR, logger=slirp.logger.name):
            assert slirp._wait_for_pid_file(str(tmp_path / "absent"), 3, threading.Event()) is None

        assert "timed out waiting for pid_file" in caplog.text and "after 3s" in caplog.text
        assert now[0] == 104.0

    def test_an_empty_file_is_not_a_pid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pid_file = tmp_path / "pid"
        pid_file.write_text("  \n")
        calls = [0]

        def sleep(delay: float) -> None:
            calls[0] += 1
            if calls[0] == 1:
                pid_file.write_text("9")

        monkeypatch.setattr(slirp.time, "sleep", sleep)

        assert slirp._wait_for_pid_file(str(pid_file), 30, threading.Event()) == 9


class _Proc:
    def __init__(self, returncode: int = 0, stderr: bytes | None = None, waits_before_exit: int = 0) -> None:
        self.pid = 555
        self.returncode = returncode
        self.stderr = _Stream(stderr) if stderr is not None else None
        self._waits = waits_before_exit
        self.wait_calls: list[float] = []

    def wait(self, timeout: float) -> int:
        self.wait_calls.append(timeout)
        if self._waits > 0:
            self._waits -= 1
            raise subprocess.TimeoutExpired("slirp4netns", timeout)
        return self.returncode


class _Stream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


@pytest.fixture
def watcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    launched: list[dict[str, Any]] = []
    state: dict[str, Any] = {"proc": _Proc(), "error": None}
    monkeypatch.setattr(slirp, "set_pdeathsig", lambda: None)

    def popen(args: list[str], **kwargs: Any) -> Any:
        launched.append({"args": args, **kwargs})
        if state["error"] is not None:
            raise state["error"]
        return state["proc"]

    monkeypatch.setattr(slirp.subprocess, "Popen", popen)

    def run(**kwargs: Any) -> tuple[int, int]:
        read_end, write_end = os.pipe()
        os.set_inheritable(write_end, True)
        arguments: dict[str, Any] = dict(
            shutdown_event=threading.Event(), pipe_w=write_end, api_socket=str(tmp_path / "a")
        )
        arguments.update(kwargs)
        slirp._run_slirp_watcher(**arguments)
        return read_end, write_end

    run.launched = launched  # type: ignore[attr-defined]
    run.state = state  # type: ignore[attr-defined]
    return run


def _closed(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


class TestWatcher:
    def test_slirp4netns_is_launched_for_the_given_pid_with_the_readiness_pipe(self, watcher: Any) -> None:
        read_end, write_end = watcher(child_pid=1234)

        (call,) = watcher.launched
        assert call["args"] == [
            "slirp4netns",
            "-c",
            "-m",
            "1500",
            "-r",
            str(write_end),
            "--api-socket",
            call["args"][7],
            "1234",
            slirp.SLIRP_INTERFACE,
        ]
        assert call["pass_fds"] == (write_end,)
        assert call["stdout"] == subprocess.DEVNULL and call["preexec_fn"] is slirp.set_pdeathsig
        assert _closed(write_end)
        os.close(read_end)

    def test_the_pid_comes_from_the_file_when_there_is_no_child_pid(self, watcher: Any, tmp_path: Path) -> None:
        pid_file = tmp_path / "pid"
        pid_file.write_text("4321")

        read_end, _ = watcher(pid_file=str(pid_file))

        assert watcher.launched[0]["args"][-2] == "4321"
        os.close(read_end)

    def test_a_known_child_pid_wins_over_the_pid_file(self, watcher: Any, tmp_path: Path) -> None:
        pid_file = tmp_path / "pid"
        pid_file.write_text("4321")

        read_end, _ = watcher(child_pid=11, pid_file=str(pid_file))

        assert watcher.launched[0]["args"][-2] == "11"
        os.close(read_end)

    def test_a_pid_file_that_never_fills_closes_the_pipe_without_launching(
        self, watcher: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(slirp, "_wait_for_pid_file", lambda *args: None)

        read_end, write_end = watcher(pid_file=str(tmp_path / "pid"))

        assert watcher.launched == [] and _closed(write_end)
        os.close(read_end)

    def test_without_any_pid_source_it_reports_and_closes_the_pipe(
        self, watcher: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR, logger=slirp.logger.name):
            read_end, write_end = watcher()

        assert "need child_pid or pid_file" in caplog.text
        assert watcher.launched == [] and _closed(write_end)
        os.close(read_end)

    def test_a_shutdown_before_the_launch_closes_the_pipe_without_launching(self, watcher: Any) -> None:
        event = threading.Event()
        event.set()

        read_end, write_end = watcher(child_pid=1, shutdown_event=event)

        assert watcher.launched == [] and _closed(write_end)
        os.close(read_end)

    def test_the_process_is_handed_to_the_holder_then_replaced_by_none(self, watcher: Any) -> None:
        holder: list[Any] = ["stale", "entries"]
        seen: list[Any] = []
        proc = _Proc()
        original_wait = proc.wait

        def wait(timeout: float) -> int:
            seen.append(list(holder))
            return original_wait(timeout)

        proc.wait = wait  # type: ignore[method-assign]
        watcher.state["proc"] = proc

        read_end, _ = watcher(child_pid=1, process_holder=holder)

        assert seen == [[proc]]
        assert holder == [None]
        os.close(read_end)

    def test_a_failure_to_launch_is_logged_and_still_closes_the_pipe(
        self, watcher: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        watcher.state["error"] = FileNotFoundError("slirp4netns")
        holder: list[Any] = []

        with caplog.at_level(logging.ERROR, logger=slirp.logger.name):
            read_end, write_end = watcher(child_pid=1, process_holder=holder)

        assert "exception launching slirp4netns" in caplog.text
        assert holder == [None] and _closed(write_end)
        os.close(read_end)

    def test_the_wait_is_polled_every_second_until_the_process_ends(self, watcher: Any) -> None:
        proc = _Proc(waits_before_exit=3)
        watcher.state["proc"] = proc

        read_end, _ = watcher(child_pid=1)

        assert proc.wait_calls == [1.0, 1.0, 1.0, 1.0]
        os.close(read_end)

    def test_a_shutdown_during_the_wait_ends_the_watch_quietly(
        self, watcher: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        event = threading.Event()
        proc = _Proc(returncode=3, stderr=b"boom", waits_before_exit=100)
        original_wait = proc.wait

        def wait(timeout: float) -> int:
            event.set()
            return original_wait(timeout)

        proc.wait = wait  # type: ignore[method-assign]
        watcher.state["proc"] = proc

        with caplog.at_level(logging.DEBUG, logger=slirp.logger.name):
            read_end, write_end = watcher(child_pid=1, shutdown_event=event)

        assert "exited with code" not in caplog.text and _closed(write_end)
        os.close(read_end)

    def test_a_shutdown_while_it_exits_hides_its_output(self, watcher: Any, caplog: pytest.LogCaptureFixture) -> None:
        event = threading.Event()
        proc = _Proc(returncode=3, stderr=b"boom")
        original_wait = proc.wait

        def wait(timeout: float) -> int:
            code = original_wait(timeout)
            event.set()
            return code

        proc.wait = wait  # type: ignore[method-assign]
        watcher.state["proc"] = proc

        with caplog.at_level(logging.DEBUG, logger=slirp.logger.name):
            read_end, _ = watcher(child_pid=1, shutdown_event=event)

        assert "boom" not in caplog.text and "exited with code" not in caplog.text
        os.close(read_end)

    def test_its_stderr_is_logged_as_an_error_and_a_bad_exit_as_a_warning(
        self, watcher: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        watcher.state["proc"] = _Proc(returncode=2, stderr=b"  cannot attach \n")

        with caplog.at_level(logging.DEBUG, logger=slirp.logger.name):
            read_end, _ = watcher(child_pid=1)

        records = {(r.levelno, r.getMessage()) for r in caplog.records}
        assert (logging.ERROR, "slirp_watcher: slirp4netns stderr: cannot attach") in records
        assert (logging.WARNING, "slirp_watcher: slirp4netns exited with code 2") in records
        assert (logging.DEBUG, "slirp_watcher: slirp4netns exited with code 2") in records
        os.close(read_end)

    @pytest.mark.parametrize("code", [0, -9])
    def test_a_clean_or_killed_exit_is_not_a_warning(
        self, watcher: Any, caplog: pytest.LogCaptureFixture, code: int
    ) -> None:
        watcher.state["proc"] = _Proc(returncode=code)

        with caplog.at_level(logging.WARNING, logger=slirp.logger.name):
            read_end, _ = watcher(child_pid=1)

        assert caplog.records == []
        os.close(read_end)

    def test_an_exit_without_stderr_logs_no_error(self, watcher: Any, caplog: pytest.LogCaptureFixture) -> None:
        watcher.state["proc"] = _Proc(returncode=0, stderr=b"")

        with caplog.at_level(logging.ERROR, logger=slirp.logger.name):
            read_end, _ = watcher(child_pid=1)

        assert caplog.records == []
        os.close(read_end)


class TestWatcherEntryPoint:
    def test_the_temporary_files_are_removed_whatever_happens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid_file, sock = tmp_path / "pid", tmp_path / "sock"
        pid_file.write_text("1")
        sock.write_text("")
        seen: dict[str, Any] = {}

        def body(*args: Any, **kwargs: Any) -> None:
            seen.update(args=args, kwargs=kwargs)
            raise RuntimeError("body failed")

        monkeypatch.setattr(slirp, "_run_slirp_watcher", body)
        event = threading.Event()

        with pytest.raises(RuntimeError, match="body failed"):
            slirp.run_slirp_watcher(event, 9, str(sock), child_pid=5, pid_file=str(pid_file), timeout=7)

        assert not pid_file.exists() and not sock.exists()
        assert seen["args"] == (event, 9, str(sock))
        assert seen["kwargs"] == {"child_pid": 5, "pid_file": str(pid_file), "process_holder": None, "timeout": 7}

    def test_the_default_timeout_is_thirty_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}
        monkeypatch.setattr(slirp, "_run_slirp_watcher", lambda *a, **k: seen.update(k))

        slirp.run_slirp_watcher(threading.Event(), 9, "/nonexistent/sock", child_pid=1)

        assert seen["timeout"] == slirp.SLIRP_WATCHER_TIMEOUT == 30


class TestTempFiles:
    def test_the_pid_file_exists_and_the_socket_path_is_free(self) -> None:
        pid_file, sock = slirp.make_slirp_temp_files()
        try:
            assert Path(pid_file).is_file() and not Path(sock).exists()
            assert pid_file != sock
        finally:
            slirp.remove_slirp_temp_files(pid_file, sock)
        assert not Path(pid_file).exists()
