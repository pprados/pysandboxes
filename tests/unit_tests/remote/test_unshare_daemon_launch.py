# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`UnshareSSEDaemon` one-shot command, slirp management and lifecycle, with every side effect recorded."""

import asyncio
import os
import stat
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote import unshare_sse_daemon as usd
from pysandboxes.remote.client_subprocess_sse_daemon import BaseSubProcessDaemon
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon


class _Threads:
    """Stands in for `threading.Thread`: records each thread and runs nothing."""

    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        record = dict(kwargs)
        self.started.append(record)
        return Mock(start=Mock(side_effect=lambda: record.setdefault("started", True)))


@pytest.fixture
def threads() -> Any:
    recorder = _Threads()
    with patch.object(usd.threading, "Thread", recorder):
        yield recorder


class _Config:
    def to_json(self) -> str:
        return '{"fake": true}'


class TestSubprocessCmd:
    def _cmd(self, daemon: UnshareSSEDaemon, tmp_path: Path, **kwargs: Any) -> tuple[Any, Any]:
        with (
            patch.object(UnshareSSEDaemon, "_prepare_unshare_config", return_value=(_Config(), [])) as prepare,
            patch.object(UnshareSSEDaemon, "_get_unshare_flags", return_value=["--flag"]) as flags,
            patch.object(usd, "slirp_extract_port_forwards", return_value="tcp:1") as ports,
        ):
            result = daemon.subprocess_cmd(EmptyRules, {"E": "v"}, tmp_path / "pipe", tmp_path, **kwargs)
        self.prepare, self.flags, self.ports = prepare, flags, ports
        return result

    def test_the_command_chains_unshare_setup_and_the_daemon(self, tmp_path: Path, threads: Any) -> None:
        daemon = UnshareSSEDaemon("tok")
        try:
            args, _ = self._cmd(daemon, tmp_path)

            config_file = (tmp_path / "unshare_config.json").resolve()
            assert args[:3] == ["unshare", "--flag", "--"]
            assert args[3:7] == [sys.executable, "-m", "pysandboxes.remote.unshare_setup", str(config_file)]
            assert args[7] == "--"
            assert args[8:] == daemon._build_daemon_cmd()
        finally:
            self._clean(daemon)

    def test_the_config_is_published_through_a_fifo_that_the_thread_fills(self, tmp_path: Path, threads: Any) -> None:
        daemon = UnshareSSEDaemon("tok")
        try:
            self._cmd(daemon, tmp_path)

            fifo = tmp_path / "unshare_config.json"
            assert stat.S_ISFIFO(fifo.stat().st_mode)
            (publisher,) = [t for t in threads.started if "target" in t and t["target"].__name__ == "publish_config"]
            assert publisher["daemon"] is True
        finally:
            self._clean(daemon)

    def test_a_stale_config_file_is_replaced_by_the_fifo(self, tmp_path: Path, threads: Any) -> None:
        stale = tmp_path / "unshare_config.json"
        stale.write_text("old")
        daemon = UnshareSSEDaemon("tok")
        try:
            self._cmd(daemon, tmp_path)

            assert stat.S_ISFIFO(stale.stat().st_mode)
        finally:
            self._clean(daemon)

    def test_the_publisher_writes_the_json_then_removes_the_fifo(self, tmp_path: Path, threads: Any) -> None:
        daemon = UnshareSSEDaemon("tok")
        try:
            self._cmd(daemon, tmp_path)
            (publisher,) = [t for t in threads.started if t["target"].__name__ == "publish_config"]
            fifo = tmp_path / "unshare_config.json"
            seen: list[str] = []

            def record(_path: Path, text: str) -> int:
                seen.append(text)
                return len(text)

            with patch.object(Path, "write_text", record):
                publisher["target"]()

            assert seen == ['{"fake": true}']
            assert not fifo.exists()
        finally:
            self._clean(daemon)

    def test_a_failing_unlink_does_not_break_the_publisher(self, tmp_path: Path, threads: Any) -> None:
        daemon = UnshareSSEDaemon("tok")
        try:
            self._cmd(daemon, tmp_path)
            (publisher,) = [t for t in threads.started if t["target"].__name__ == "publish_config"]
            with (
                patch.object(Path, "write_text", return_value=0),
                patch.object(Path, "unlink", side_effect=PermissionError("no")),
            ):
                publisher["target"]()
        finally:
            self._clean(daemon)

    def test_the_debug_mode_writes_a_plain_file_and_keeps_it(
        self, tmp_path: Path, threads: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.chdir(tmp_path)
        daemon = UnshareSSEDaemon("tok")
        try:
            with patch.object(usd, "DEBUG_LAUNCH", True):
                args, _ = self._cmd(daemon, tmp_path / "other")
                (publisher,) = [t for t in threads.started if t["target"].__name__ == "publish_config"]
                publisher["target"]()

            written = tmp_path / "tmp" / "unshare_config.json"
            assert written.read_text() == '{"fake": true}'
            assert args[6] == str(written.resolve())
        finally:
            self._clean(daemon)

    def test_the_environment_carries_the_slirp_pipe_and_the_python_path(
        self, tmp_path: Path, threads: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("PYTHONPATH", "/existing")
        daemon = UnshareSSEDaemon("tok")
        try:
            _, extra = self._cmd(daemon, tmp_path)

            assert extra == {
                "PID_FILE": daemon._slirp_pid_file,
                "SLIRP_READY_FD": str(daemon._slirp_pipe_r),
                "PYTHONPATH": f"{os.getcwd()}:/existing",
            }
        finally:
            self._clean(daemon)

    def test_without_a_python_path_the_project_root_stands_alone(
        self, tmp_path: Path, threads: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.delenv("PYTHONPATH", raising=False)
        daemon = UnshareSSEDaemon("tok")
        try:
            _, extra = self._cmd(daemon, tmp_path)

            assert extra["PYTHONPATH"] == os.getcwd()
        finally:
            self._clean(daemon)

    def test_an_empty_python_path_is_ignored(self, tmp_path: Path, threads: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv("PYTHONPATH", "")
        daemon = UnshareSSEDaemon("tok")
        try:
            _, extra = self._cmd(daemon, tmp_path)

            assert extra["PYTHONPATH"] == os.getcwd()
        finally:
            self._clean(daemon)

    def test_the_slirp_state_and_the_ports_are_kept_for_the_launch(self, tmp_path: Path, threads: Any) -> None:
        daemon = UnshareSSEDaemon("tok")
        try:
            self._cmd(daemon, tmp_path)

            assert daemon._ports_spec == "tcp:1"
            self.ports.assert_called_once_with(EmptyRules, daemon.port)
            assert daemon._slirp_pid_file_for_watcher == daemon._slirp_pid_file
            assert daemon._slirp_api_socket_for_watcher == daemon._slirp_api_socket
            assert daemon._slirp_pipe_r != daemon._slirp_pipe_w
            assert len(daemon._chroot_dirs) == 1
            self.prepare.assert_called_once_with(EmptyRules, tmp_path / "pipe", daemon._chroot_dirs[0])
        finally:
            self._clean(daemon)

    def test_the_flags_are_computed_from_a_copy_of_the_environment(self, tmp_path: Path, threads: Any) -> None:
        daemon = UnshareSSEDaemon("tok")
        envs = {"E": "v"}
        try:
            with (
                patch.object(UnshareSSEDaemon, "_prepare_unshare_config", return_value=(_Config(), [])),
                patch.object(UnshareSSEDaemon, "_get_unshare_flags", return_value=[]) as flags,
                patch.object(usd, "slirp_extract_port_forwards", return_value=""),
            ):
                daemon.subprocess_cmd(EmptyRules, envs, tmp_path / "pipe", tmp_path)

            (_, passed), _ = flags.call_args
            assert passed == envs and passed is not envs
        finally:
            self._clean(daemon)

    @staticmethod
    def _clean(daemon: UnshareSSEDaemon) -> None:
        for fd in (getattr(daemon, "_slirp_pipe_r", -1), getattr(daemon, "_slirp_pipe_w", -1)):
            try:
                os.close(fd)
            except OSError:
                pass
        daemon._remove_chroot_dirs()
        for name in ("_slirp_pid_file", "_slirp_api_socket"):
            value = getattr(daemon, name, None)
            if value:
                Path(value).unlink(missing_ok=True)


class TestLaunchExtras:
    def test_the_slirp_read_end_is_passed_to_the_child(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        daemon._slirp_pipe_r = 42

        preexec, fds = daemon.get_launch_extras()

        assert fds == (42,)
        assert preexec() is None


class TestOnProcessLaunched:
    def _daemon(self, tmp_path: Path, ports: str = "") -> UnshareSSEDaemon:
        daemon = UnshareSSEDaemon("tok")
        daemon._slirp_pipe_r, daemon._slirp_pipe_w = os.pipe()
        daemon._slirp_pid_file_for_watcher = str(tmp_path / "pid")
        daemon._slirp_api_socket_for_watcher = str(tmp_path / "api.sock")
        daemon._ports_spec = ports
        return daemon

    def test_the_read_end_is_closed_and_the_pid_is_written(self, tmp_path: Path, threads: Any) -> None:
        daemon = self._daemon(tmp_path)
        read_fd = daemon._slirp_pipe_r
        try:
            daemon.on_process_launched(1234)

            assert (tmp_path / "pid").read_text() == "1234"
            with pytest.raises(OSError):
                os.fstat(read_fd)
        finally:
            os.close(daemon._slirp_pipe_w)

    def test_a_read_end_already_closed_is_tolerated(self, tmp_path: Path, threads: Any) -> None:
        daemon = self._daemon(tmp_path)
        os.close(daemon._slirp_pipe_r)
        try:
            daemon.on_process_launched(7)

            assert (tmp_path / "pid").read_text() == "7"
        finally:
            os.close(daemon._slirp_pipe_w)

    def test_the_watcher_thread_receives_the_slirp_state(self, tmp_path: Path, threads: Any) -> None:
        daemon = self._daemon(tmp_path)
        try:
            daemon.on_process_launched(1)

            (watcher,) = threads.started
            assert watcher["target"] is usd.slirp_run_watcher
            assert watcher["args"] == (daemon._slirp_shutdown_event, daemon._slirp_pipe_w, str(tmp_path / "api.sock"))
            assert watcher["kwargs"] == {
                "pid_file": str(tmp_path / "pid"),
                "process_holder": daemon._slirp_process_holder,
                "timeout": usd.SLIRP_WATCHER_TIMEOUT,
            }
            assert watcher["daemon"] is True
            assert watcher["started"] is True
        finally:
            os.close(daemon._slirp_pipe_w)

    def test_the_forwarded_ports_get_their_own_thread(self, tmp_path: Path, threads: Any) -> None:
        daemon = self._daemon(tmp_path, ports="tcp:80")
        try:
            daemon.on_process_launched(1)

            watcher, forwarding = threads.started
            assert forwarding["target"] is usd.slirp_setup_port_forwarding
            assert forwarding["args"] == (str(tmp_path / "api.sock"), "tcp:80")
            assert forwarding["daemon"] is True
            assert forwarding["started"] is True
        finally:
            os.close(daemon._slirp_pipe_w)


class TestKillSlirp:
    def test_the_process_is_killed_then_waited_for_five_seconds(self, tmp_path: Path) -> None:
        daemon = UnshareSSEDaemon("tok")
        process = Mock()
        daemon._slirp_process_holder[0] = process
        daemon._slirp_pid_file, daemon._slirp_api_socket = "pid", "sock"

        with patch.object(usd, "slirp_remove_temp_files") as remove:
            daemon._kill_slirp()

        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)
        remove.assert_called_once_with("pid", "sock")
        assert daemon._slirp_pid_file is None and daemon._slirp_api_socket is None

    def test_a_process_that_refuses_to_die_does_not_block_the_cleanup(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        process = Mock(kill=Mock(side_effect=ProcessLookupError()))
        daemon._slirp_process_holder[0] = process

        with patch.object(usd, "slirp_remove_temp_files") as remove:
            daemon._kill_slirp()

        assert daemon._slirp_process_holder[0] is None
        remove.assert_called_once()

    def test_an_emptied_holder_is_tolerated(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        daemon._slirp_process_holder.clear()

        with patch.object(usd, "slirp_remove_temp_files") as remove:
            daemon._kill_slirp()

        remove.assert_called_once()


class TestShutdown:
    def test_the_parent_shuts_down_then_slirp_and_the_roots_are_cleaned_in_threads(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        order: list[str] = []

        async def parent(self: Any, graceful: bool) -> None:
            order.append(f"parent:{graceful}:{daemon._slirp_shutdown_event.is_set()}")

        with (
            patch.object(BaseSubProcessDaemon, "_shutdown", parent),
            patch.object(UnshareSSEDaemon, "_kill_slirp", side_effect=lambda: order.append("slirp")),
            patch.object(UnshareSSEDaemon, "_remove_chroot_dirs", side_effect=lambda: order.append("roots")),
        ):
            asyncio.run(daemon._shutdown(False))

        assert order == ["parent:False:True", "slirp", "roots"]

    def test_the_cleanup_runs_even_when_the_parent_fails(self) -> None:
        daemon = UnshareSSEDaemon("tok")

        with (
            patch.object(BaseSubProcessDaemon, "_shutdown", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(UnshareSSEDaemon, "_kill_slirp") as kill,
            patch.object(UnshareSSEDaemon, "_remove_chroot_dirs") as roots,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                asyncio.run(daemon._shutdown())

        kill.assert_called_once_with()
        roots.assert_called_once_with()

    def test_the_default_shutdown_is_graceful(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        parent = AsyncMock()

        with (
            patch.object(BaseSubProcessDaemon, "_shutdown", parent),
            patch.object(UnshareSSEDaemon, "_kill_slirp"),
            patch.object(UnshareSSEDaemon, "_remove_chroot_dirs"),
        ):
            asyncio.run(daemon._shutdown())

        parent.assert_awaited_once_with(True)


class TestStart:
    def _start(self, daemon: UnshareSSEDaemon, rules: Any) -> Any:
        async def run() -> Any:
            with (
                patch.object(UnshareSSEDaemon, "_launch", AsyncMock()) as launch,
                patch.object(UnshareSSEDaemon, "_watchdog_loop", AsyncMock()) as watchdog,
                patch.object(usd, "find_free_port", return_value=4321),
            ):
                await daemon._start(rules, envs={"A": "b"}, log_level=7, init_fn=None)
                task = daemon._watchdog
                assert task is not None
                await task
                return launch, watchdog, task

        return asyncio.run(run())

    def test_a_free_port_is_chosen_when_the_rules_leave_it_open(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        daemon.restart = 9

        launch, watchdog, task = self._start(daemon, EmptyRules._replace(port=-1))

        assert daemon.port == 4321
        assert daemon.restart == 0
        launch.assert_awaited_once_with(
            EmptyRules._replace(port=-1), envs={"A": "b"}, log_level=7, init_fn=None, first=True
        )
        watchdog.assert_called_once_with(EmptyRules._replace(port=-1), envs={"A": "b"}, log_level=7, init_fn=None)
        assert task.get_name() == "ControlDaemon"

    def test_a_port_fixed_by_the_rules_is_kept(self) -> None:
        daemon = UnshareSSEDaemon("tok")

        self._start(daemon, EmptyRules._replace(port=5555))

        assert daemon.port == 5555
