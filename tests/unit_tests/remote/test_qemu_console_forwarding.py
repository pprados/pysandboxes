# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""QEMU serial console: sentinel filtering, line rebuilding, the guest stderr tail and the exit code poll."""

import asyncio
import io
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import qemu_guest_console_io as console
from pysandboxes.remote.qemu_guest_console_io import PYTHON_OUTPUT_END as END
from pysandboxes.remote.qemu_guest_console_io import PYTHON_OUTPUT_START as START


class TestTerminalText:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", ""),
            ("abc", "abc"),
            ("a\n", "a\r\n"),
            ("a\r\n", "a\r\n"),
            ("a\r\r\n", "a\r\n"),
            ("\n", "\r\n"),
            ("a\rb", "a\rb"),
        ],
    )
    def test_a_line_ends_with_a_single_crlf(self, text: str, expected: str) -> None:
        assert console._qemu_console_text_for_terminal(text) == expected


class TestSentinelState:
    def _feed(self, lines: list[str]) -> list[bool]:
        state = [console._FORWARD_STATE_WAITING]
        return [console._qemu_forward_state_for_line(line, state) for line in lines]

    def test_only_the_lines_between_the_sentinels_are_forwarded(self) -> None:
        assert self._feed(["boot\n", f"{START}\n", "42\n", "43\n", f"{END}\n", "halt\n"]) == [
            False,
            False,
            True,
            True,
            False,
            False,
        ]

    def test_the_start_sentinel_may_sit_inside_a_longer_line(self) -> None:
        assert self._feed([f"noise {START} noise", "out"]) == [False, True]

    def test_after_the_end_nothing_is_forwarded_even_if_the_start_comes_back(self) -> None:
        assert self._feed([START, "a", END, START, "b"]) == [False, True, False, False, False]

    def test_the_end_sentinel_before_the_start_does_not_matter(self) -> None:
        state = [console._FORWARD_STATE_WAITING]

        assert console._qemu_forward_state_for_line(END, state) is False
        assert state == [console._FORWARD_STATE_WAITING]

    def test_the_state_values_follow_the_phases(self) -> None:
        state = [console._FORWARD_STATE_WAITING]
        console._qemu_forward_state_for_line(START, state)
        assert state == [console._FORWARD_STATE_FORWARDING]
        console._qemu_forward_state_for_line(END, state)
        assert state == [console._FORWARD_STATE_STOPPED]


class TestMirror:
    def test_a_line_is_logged_at_debug_without_its_line_ending(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("mirror-test")

        with caplog.at_level(logging.DEBUG, logger="mirror-test"):
            console._mirror_line(logger, "hello\r\n")

        assert [(r.levelno, r.getMessage()) for r in caplog.records] == [(logging.DEBUG, "[qemu-serial] hello")]

    @pytest.mark.parametrize("text", ["", "\r\n", "\n"])
    def test_an_empty_line_is_not_logged(self, caplog: pytest.LogCaptureFixture, text: str) -> None:
        with caplog.at_level(logging.DEBUG, logger="mirror-test"):
            console._mirror_line(logging.getLogger("mirror-test"), text)

        assert caplog.records == []

    def test_without_a_logger_nothing_happens(self) -> None:
        console._mirror_line(None, "text")


class TestPrefix:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("[   12.525772] cloud-init[672]: hello\n", "hello\n"),
            ("[ 1.0] prog[1]: 42\n", "42\n"),
            ("  [  3.5] a-b[10]:no space\n", "no space\n"),
            ("plain line\n", "plain line\n"),
            ("[abc] prog[1]: x\n", "[abc] prog[1]: x\n"),
        ],
    )
    def test_the_kernel_prefix_is_stripped_with_the_space_that_follows_it(self, raw: str, expected: str) -> None:
        assert console._QEMU_CONSOLE_PREFIX.sub("", raw) == expected


class _Out(io.StringIO):
    pass


async def _emit(raw: bytes, state: list[int] | None = None, **kwargs: Any) -> tuple[str, list[int]]:
    out = _Out()
    state = [console._FORWARD_STATE_FORWARDING] if state is None else state
    options: dict[str, Any] = dict(forward_all=False, tee_file=None, tee_lock=None, mirror_logger=None)
    options.update(kwargs)
    await console._qemu_emit_qemu_console_line(raw, out, state, **options)
    return out.getvalue(), state


class TestEmit:
    async def test_an_empty_chunk_prints_nothing(self) -> None:
        assert (await _emit(b""))[0] == ""

    async def test_a_forwarded_line_is_stripped_and_given_a_crlf(self) -> None:
        out, _ = await _emit(b"[  1.5] prog[2]: hello\n")

        assert out == "hello\r\n"

    async def test_invalid_utf8_is_replaced_not_fatal(self) -> None:
        out, _ = await _emit(b"caf\xe9\n")

        assert out == "caf�\r\n"

    async def test_outside_the_sentinels_nothing_is_printed(self) -> None:
        out, _ = await _emit(b"boot noise\n", [console._FORWARD_STATE_WAITING])

        assert out == ""

    async def test_forward_all_prints_everything_and_ignores_the_state(self) -> None:
        out, state = await _emit(b"boot noise\n", [console._FORWARD_STATE_WAITING], forward_all=True)

        assert out == "boot noise\r\n"
        assert state == [console._FORWARD_STATE_WAITING]

    async def test_a_filtered_chunk_advances_the_state(self) -> None:
        _, state = await _emit(f"{START}\n".encode(), [console._FORWARD_STATE_WAITING])

        assert state == [console._FORWARD_STATE_FORWARDING]

    async def test_the_tee_receives_the_raw_text_even_when_the_line_is_filtered(self) -> None:
        tee = io.StringIO()
        flushed: list[bool] = []
        tee.flush = lambda: flushed.append(True)  # type: ignore[method-assign]

        out, _ = await _emit(
            b"[  1.5] prog[2]: noise\n",
            [console._FORWARD_STATE_WAITING],
            tee_file=tee,
            tee_lock=asyncio.Lock(),
        )

        assert out == ""
        assert tee.getvalue() == "[  1.5] prog[2]: noise\n"
        assert flushed == [True]

    async def test_a_tee_without_a_lock_is_a_programming_error(self) -> None:
        with pytest.raises(AssertionError):
            await _emit(b"x\n", tee_file=io.StringIO(), tee_lock=None)

    async def test_the_forwarded_line_is_mirrored_to_the_log(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="mirror-test"):
            await _emit(b"hello\n", mirror_logger=logging.getLogger("mirror-test"))

        assert "[qemu-serial] hello" in caplog.text

    async def test_a_filtered_line_is_not_mirrored(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="mirror-test"):
            await _emit(b"hello\n", [console._FORWARD_STATE_WAITING], mirror_logger=logging.getLogger("mirror-test"))

        assert caplog.records == []


def _stream(*chunks: bytes, eof: bool = True) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    for chunk in chunks:
        reader.feed_data(chunk)
    if eof:
        reader.feed_eof()
    return reader


async def _forward(stream: Any, *, is_stderr: bool = False, state: list[int] | None = None, **kwargs: Any) -> str:
    import sys
    from unittest.mock import patch

    out = _Out()
    target = "stderr" if is_stderr else "stdout"
    with patch.object(sys, target, out):
        await console._qemu_read_and_forward(
            stream, is_stderr, state if state is not None else [console._FORWARD_STATE_FORWARDING], **kwargs
        )
    return out.getvalue()


class TestReadAndForward:
    async def test_no_stream_is_a_no_op(self) -> None:
        assert await _forward(None) == ""

    async def test_lines_in_one_chunk_are_printed_one_by_one(self) -> None:
        assert await _forward(_stream(b"one\ntwo\nthree\n")) == "one\r\ntwo\r\nthree\r\n"

    async def test_a_line_split_across_chunks_is_rebuilt(self) -> None:
        assert await _forward(_stream(b"hel", b"lo wor", b"ld\nnext\n")) == "hello world\r\nnext\r\n"

    async def test_a_last_line_without_newline_is_still_printed_at_eof(self) -> None:
        assert await _forward(_stream(b"done\ntail")) == "done\r\ntail"

    async def test_stderr_goes_to_stderr(self) -> None:
        assert await _forward(_stream(b"oops\n"), is_stderr=True) == "oops\r\n"

    async def test_the_sentinels_filter_the_stream(self) -> None:
        data = f"boot\n{START}\nvisible\n{END}\nhalt\n".encode()

        assert await _forward(_stream(data), state=[console._FORWARD_STATE_WAITING]) == "visible\r\n"

    async def test_a_progress_line_ending_in_a_carriage_return_is_printed_as_is(self) -> None:
        out = await _forward(_stream(b"progress 1\rprogress 2\rdone\n"), forward_all=True)

        assert out == "progress 1\rprogress 2\rdone\r\n"

    @pytest.mark.parametrize(
        ("data", "lines"),
        [
            (b"a\nb\rc\n", ["a", "b", "c"]),
            (b"a\rb\nc\n", ["a", "b", "c"]),
            (b"p1\rp2\rp3\n", ["p1", "p2", "p3"]),
        ],
    )
    async def test_when_everything_is_forwarded_a_carriage_return_also_ends_a_line(
        self, caplog: pytest.LogCaptureFixture, data: bytes, lines: list[str]
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="mirror-test"):
            await _forward(_stream(data), forward_all=True, mirror_logger=logging.getLogger("mirror-test"))

        assert [r.getMessage() for r in caplog.records] == [f"[qemu-serial] {line}" for line in lines]

    async def test_a_carriage_return_alone_does_not_end_a_filtered_line(self, caplog: pytest.LogCaptureFixture) -> None:
        data = f"{START}\nprogress 1\rprogress 2\n".encode()

        with caplog.at_level(logging.DEBUG, logger="mirror-test"):
            out = await _forward(
                _stream(data), state=[console._FORWARD_STATE_WAITING], mirror_logger=logging.getLogger("mirror-test")
            )

        assert out == "progress 1\rprogress 2\r\n"
        assert [r.getMessage() for r in caplog.records] == ["[qemu-serial] progress 1\rprogress 2"]

    async def test_a_line_that_never_ends_is_flushed_at_the_buffer_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(console, "_QEMU_CONSOLE_BUF_MAX", 8)

        out = await _forward(_stream(b"12345678", b"9\n"))

        assert out == "12345678" + "9\r\n"

    async def test_a_reset_connection_ends_the_drain_and_keeps_what_was_read(self) -> None:
        class Reset:
            def __init__(self) -> None:
                self.calls = 0

            async def read(self, n: int) -> bytes:
                self.calls += 1
                if self.calls == 1:
                    return b"kept\npartial"
                raise ConnectionResetError

        assert await _forward(Reset()) == "kept\r\npartial"

    async def test_the_raw_stream_reaches_the_tee_and_the_mirror(self, caplog: pytest.LogCaptureFixture) -> None:
        tee = io.StringIO()

        with caplog.at_level(logging.DEBUG, logger="mirror-test"):
            await _forward(
                _stream(b"a\nb\n"),
                tee_file=tee,
                tee_lock=asyncio.Lock(),
                mirror_logger=logging.getLogger("mirror-test"),
            )

        assert tee.getvalue() == "a\nb\n"
        assert "[qemu-serial] a" in caplog.text and "[qemu-serial] b" in caplog.text


class _Process:
    def __init__(self, stdout: Any, stderr: Any, code: int | None = 0) -> None:
        self.stdout, self.stderr, self._code = stdout, stderr, code

    async def wait(self) -> int | None:
        return self._code


class TestDrainTasks:
    async def test_two_named_tasks_share_one_state(self, capsys: pytest.CaptureFixture[str]) -> None:
        process = _Process(_stream(f"{START}\n".encode()), _stream(b"x\n"))

        tasks = console.start_qemu_serial_drain_tasks(process, forward_all=False)  # type: ignore[arg-type]
        await asyncio.gather(*tasks)

        assert [t.get_name() for t in tasks] == ["qemu-serial-stdout", "qemu-serial-stderr"]
        assert capsys.readouterr().out == ""

    async def test_a_tee_file_gets_a_lock_and_the_raw_output(self) -> None:
        tee = io.StringIO()
        process = _Process(_stream(b"a\n"), _stream(b"b\n"))

        await asyncio.gather(*console.start_qemu_serial_drain_tasks(process, forward_all=True, tee_file=tee))  # type: ignore[arg-type]

        assert sorted(tee.getvalue().split()) == ["a", "b"]


class TestWaitAndFilter:
    async def test_it_returns_the_exit_code_after_forwarding_the_console(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = f"boot\n{START}\nresult\n{END}\n".encode()
        process = _Process(_stream(data), _stream())

        code = await console.qemu_wait_and_filter_console(process, forward_all=False)  # type: ignore[arg-type]

        assert code == 0
        assert capsys.readouterr().out == "result\r\n"

    @pytest.mark.parametrize(("exit_code", "expected"), [(3, 3), (0, 0), (None, -1)])
    async def test_a_missing_exit_code_is_minus_one(self, exit_code: int | None, expected: int) -> None:
        process = _Process(_stream(), _stream(), exit_code)

        assert await console.qemu_wait_and_filter_console(process) == expected  # type: ignore[arg-type]

    async def test_a_tee_without_a_lock_gets_one(self) -> None:
        tee = io.StringIO()
        process = _Process(_stream(b"a\n"), _stream())

        await console.qemu_wait_and_filter_console(process, forward_all=True, tee_file=tee)  # type: ignore[arg-type]

        assert tee.getvalue() == "a\n"


class TestGuestStderrTail:
    def test_new_content_is_copied_once(self, tmp_path: Path) -> None:
        path, out = tmp_path / "stderr", io.StringIO()
        tail = console.GuestStderrTail(path, out=out)

        tail._drain()
        assert out.getvalue() == ""
        path.write_text("one\n")
        tail._drain()
        tail._drain()
        with path.open("a") as f:
            f.write("two\n")
        tail._drain()

        assert out.getvalue() == "one\ntwo\n"

    def test_a_missing_file_means_nothing_yet(self, tmp_path: Path) -> None:
        out = io.StringIO()

        console.GuestStderrTail(tmp_path / "absent", out=out)._drain()

        assert out.getvalue() == ""

    def test_invalid_bytes_are_replaced(self, tmp_path: Path) -> None:
        path, out = tmp_path / "stderr", io.StringIO()
        path.write_bytes(b"caf\xe9\n")

        console.GuestStderrTail(path, out=out)._drain()

        assert out.getvalue() == "caf�\n"

    def test_the_output_is_flushed(self, tmp_path: Path) -> None:
        path = tmp_path / "stderr"
        path.write_text("x\n")
        flushed: list[bool] = []
        out = io.StringIO()
        out.flush = lambda: flushed.append(True)  # type: ignore[method-assign]

        console.GuestStderrTail(path, out=out)._drain()

        assert flushed == [True]

    def test_the_default_output_is_stderr(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "stderr"
        path.write_text("x\n")

        console.GuestStderrTail(path)._drain()

        assert capsys.readouterr().err == "x\n"

    def test_the_tail_forwards_while_running_and_drains_what_remains_at_exit(self, tmp_path: Path) -> None:
        path, out = tmp_path / "stderr", io.StringIO()
        path.write_text("early\n")

        with console.GuestStderrTail(path, out=out, interval_s=0.01):
            deadline = __import__("time").monotonic() + 5
            while "early" not in out.getvalue() and __import__("time").monotonic() < deadline:
                __import__("time").sleep(0.01)
            assert out.getvalue() == "early\n"
            with path.open("a") as f:
                f.write("late\n")

        assert out.getvalue() == "early\nlate\n"

    def test_the_thread_is_a_named_daemon_and_stops_at_exit(self, tmp_path: Path) -> None:
        tail = console.GuestStderrTail(tmp_path / "stderr", out=io.StringIO(), interval_s=0.01)

        with tail:
            assert tail._thread is not None
            assert tail._thread.daemon is True and tail._thread.name == "qemu-guest-stderr"
            assert tail._thread.is_alive()

        assert not tail._thread.is_alive()


class TestExitCode:
    def test_the_code_written_by_the_guest_is_read(self, tmp_path: Path) -> None:
        path = tmp_path / "exitcode"
        path.write_text("3\n")

        assert console.read_qemu_guest_exitcode(path) == 3

    def test_a_negative_code_is_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "exitcode"
        path.write_text("-9")

        assert console.read_qemu_guest_exitcode(path) == -9

    def test_a_missing_file_gives_none_after_the_wait(self, tmp_path: Path) -> None:
        assert console.read_qemu_guest_exitcode(tmp_path / "absent", max_wait_s=0.1, interval_s=0.01) is None

    def test_garbage_gives_none(self, tmp_path: Path) -> None:
        path = tmp_path / "exitcode"
        path.write_text("not a number")

        assert console.read_qemu_guest_exitcode(path, max_wait_s=0.1, interval_s=0.01) is None

    def test_a_file_completed_during_the_wait_is_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "exitcode"
        path.write_text("")
        sleeps: list[float] = []

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            path.write_text("7")

        monkeypatch.setattr(console.time, "sleep", sleep)

        assert console.read_qemu_guest_exitcode(path, max_wait_s=5, interval_s=0.05) == 7
        assert sleeps == [0.05]

    def test_the_poll_stops_at_the_deadline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        now = [100.0]
        monkeypatch.setattr(console.time, "monotonic", lambda: now[0])
        monkeypatch.setattr(console.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))

        assert console.read_qemu_guest_exitcode(tmp_path / "absent", max_wait_s=1.0, interval_s=0.25) is None
        assert now[0] == 101.0

    def test_the_defaults_are_a_short_poll(self) -> None:
        import inspect

        parameters = inspect.signature(console.read_qemu_guest_exitcode).parameters
        assert (parameters["max_wait_s"].default, parameters["interval_s"].default) == (3.0, 0.05)
        assert SimpleNamespace(**{k: v.default for k, v in parameters.items() if k != "exitcode_file"})


class _Chunks:
    """A stream that hands out one chunk per read, as a console does between two writes of the guest."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)

    async def read(self, n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


async def _lines(data: list[bytes], caplog: pytest.LogCaptureFixture, **kwargs: Any) -> list[str]:
    """The lines the drain rebuilt, as the mirror logger saw them."""
    with caplog.at_level(logging.DEBUG, logger="mirror-test"):
        await _forward(_Chunks(*data), mirror_logger=logging.getLogger("mirror-test"), **kwargs)
    return [r.getMessage().removeprefix("[qemu-serial] ") for r in caplog.records]


class TestLineRebuilding:
    async def test_chunks_are_joined_into_whole_lines(self, caplog: pytest.LogCaptureFixture) -> None:
        assert await _lines([b"hel", b"lo wor", b"ld\nnext\n"], caplog) == ["hello world", "next"]

    async def test_a_newline_at_the_very_start_ends_an_empty_line(self, caplog: pytest.LogCaptureFixture) -> None:
        assert await _lines([b"\nx\n"], caplog) == ["x"]
        assert await _forward(_stream(b"\nx\n")) == "\r\nx\r\n"

    async def test_a_carriage_return_at_the_very_start_ends_an_empty_line_when_everything_is_forwarded(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert await _lines([b"\rabc\n"], caplog, forward_all=True) == ["abc"]

    async def test_a_leading_newline_is_a_line_when_everything_is_forwarded(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert await _forward(_stream(b"\nx\n"), forward_all=True) == "\r\nx\r\n"

    async def test_a_line_too_long_is_cut_at_the_limit_and_the_rest_continues(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(console, "_QEMU_CONSOLE_BUF_MAX", 8)

        assert await _lines([b"123456789", b"AB\n"], caplog) == ["123456789", "AB"]

    async def test_a_line_exactly_at_the_limit_is_cut(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(console, "_QEMU_CONSOLE_BUF_MAX", 8)

        assert await _lines([b"12345678", b"AB\n"], caplog) == ["12345678", "AB"]

    async def test_a_short_partial_line_waits_for_its_end(self, caplog: pytest.LogCaptureFixture) -> None:
        assert await _lines([b"12", b"34\n"], caplog) == ["1234"]


class _CountingLock:
    def __init__(self) -> None:
        self.entered = 0

    async def __aenter__(self) -> None:
        self.entered += 1

    async def __aexit__(self, *_: object) -> None:
        return None


class TestTeeLock:
    async def test_the_lock_given_by_the_caller_is_the_one_used(self) -> None:
        lock = _CountingLock()
        process = _Process(_stream(b"a\n"), _stream())

        await console.qemu_wait_and_filter_console(
            process, forward_all=True, tee_file=io.StringIO(), tee_lock=lock  # type: ignore[arg-type]
        )

        assert lock.entered == 1
