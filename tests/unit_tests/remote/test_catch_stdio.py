"""Unit tests for pysandboxes.remote.catch_stdio module."""

import asyncio
import contextvars
import io
import queue
import sys
from unittest.mock import Mock, patch

import pytest

from pysandboxes.remote.catch_stdio import (
    QueueStringIO,
    WrapperIO,
    acatch_stdio,
    catch_stdio,
)


class TestQueueStringIO:
    """Test cases for QueueStringIO class."""

    def test_queue_string_io_initialization(self) -> None:
        """Test QueueStringIO initialization."""
        test_queue: queue.Queue = queue.Queue()
        qsio = QueueStringIO("stdout", test_queue)

        assert qsio.type == "stdout"
        assert qsio._message_queue == test_queue
        assert isinstance(qsio._buffer, io.StringIO)

    def test_queue_string_io_write_with_sync_queue(self) -> None:
        """Test writing to QueueStringIO with synchronous queue."""
        test_queue: queue.Queue = queue.Queue()
        qsio = QueueStringIO("stdout", test_queue)

        result = qsio.write("Hello, World!")

        assert result == 13  # Length of written string
        assert qsio._buffer.getvalue() == "Hello, World!"

        # Check queue received the message
        message = test_queue.get_nowait()
        assert message == {"stdout": "Hello, World!"}

    def test_queue_string_io_write_with_async_queue(self) -> None:
        """Test writing to QueueStringIO with asynchronous queue."""
        test_queue: asyncio.Queue = asyncio.Queue()
        qsio = QueueStringIO("stderr", test_queue)

        result = qsio.write("Error message")

        assert result == 13  # Length of written string
        assert qsio._buffer.getvalue() == "Error message"

        # Check async queue received the message
        try:
            message = test_queue.get_nowait()
            assert message == {"stderr": "Error message"}
        except asyncio.QueueEmpty:
            pytest.fail("Message should have been added to async queue")

    def test_queue_string_io_write_without_queue(self) -> None:
        """Test writing to QueueStringIO without queue."""
        qsio = QueueStringIO("stdout", None)

        result = qsio.write("No queue test")

        assert result == 13
        assert qsio._buffer.getvalue() == "No queue test"

    def test_queue_string_io_getvalue(self) -> None:
        """Test getting accumulated value from QueueStringIO."""
        qsio = QueueStringIO("stdout", None)

        qsio.write("First line\n")
        qsio.write("Second line\n")

        result = qsio.getvalue()
        assert result == "First line\nSecond line\n"

    def test_queue_string_io_flush(self) -> None:
        """Test flush method of QueueStringIO."""
        qsio = QueueStringIO("stdout", None)

        # Flush should not raise an exception
        qsio.flush()

        # Write some data and flush again
        qsio.write("test data")
        qsio.flush()
        assert qsio.getvalue() == "test data"

    def test_queue_string_io_multiple_writes(self) -> None:
        """Test multiple writes to QueueStringIO."""
        test_queue: queue.Queue = queue.Queue()
        qsio = QueueStringIO("stdout", test_queue)

        qsio.write("Line 1\n")
        qsio.write("Line 2\n")
        qsio.write("Line 3")

        assert qsio.getvalue() == "Line 1\nLine 2\nLine 3"

        # Each write should add a message to queue
        messages = []
        while not test_queue.empty():
            messages.append(test_queue.get_nowait())

        expected_messages = [
            {"stdout": "Line 1\n"},
            {"stdout": "Line 2\n"},
            {"stdout": "Line 3"},
        ]
        assert messages == expected_messages


class TestWrapperIO:
    """Test cases for WrapperIO class."""

    def test_wrapper_io_initialization(self) -> None:
        """Test WrapperIO initialization."""
        test_context = contextvars.ContextVar("test_context", default=sys.stdout)
        wrapper = WrapperIO(test_context)

        assert wrapper._context == test_context
        assert wrapper._old is None

    def test_wrapper_io_set_context(self) -> None:
        """Test setting context in WrapperIO."""
        original_stream = io.StringIO()
        test_context = contextvars.ContextVar("test_context", default=original_stream)
        wrapper = WrapperIO(test_context)

        new_stream = io.StringIO()
        wrapper.set_context(new_stream)

        assert wrapper._old == original_stream
        assert test_context.get() == new_stream

    def test_wrapper_io_write(self) -> None:
        """Test writing to WrapperIO."""
        test_stream = io.StringIO()
        test_context = contextvars.ContextVar("test_context", default=test_stream)
        wrapper = WrapperIO(test_context)

        result = wrapper.write("Test message")

        assert result == 12  # Length of "Test message"
        assert test_stream.getvalue() == "Test message"

    def test_wrapper_io_flush(self) -> None:
        """Test flushing WrapperIO."""
        test_stream = Mock()
        test_context = contextvars.ContextVar("test_context", default=test_stream)
        wrapper = WrapperIO(test_context)

        wrapper.flush()

        test_stream.flush.assert_called_once()

    def test_wrapper_io_getattr_delegation(self) -> None:
        """Test attribute delegation in WrapperIO."""
        mock_stream = Mock()
        mock_stream.some_attribute = "test_value"
        test_context = contextvars.ContextVar("test_context", default=mock_stream)
        wrapper = WrapperIO(test_context)
        wrapper._old = mock_stream

        result = wrapper.some_attribute

        assert result == "test_value"

    def test_wrapper_io_setattr_delegation(self) -> None:
        """Test attribute setting delegation in WrapperIO."""
        mock_stream = Mock()
        test_context = contextvars.ContextVar("test_context", default=mock_stream)
        wrapper = WrapperIO(test_context)
        wrapper._old = mock_stream

        wrapper.some_attribute = "new_value"

        assert mock_stream.some_attribute == "new_value"

    def test_wrapper_io_special_attributes(self) -> None:
        """Test that special attributes are not delegated."""
        mock_stream = Mock()
        test_context = contextvars.ContextVar("test_context", default=mock_stream)
        wrapper = WrapperIO(test_context)

        # These should be set on wrapper, not delegated
        wrapper._context = test_context
        wrapper._old = mock_stream

        assert wrapper._context == test_context
        assert wrapper._old == mock_stream


class TestCatchStdio:
    """Test cases for catch_stdio function."""

    @patch("pysandboxes.remote.catch_stdio.get_sandbox_loop")
    @patch("asyncio.get_event_loop")
    @patch("asyncio.run_coroutine_threadsafe")
    def test_catch_stdio_basic_function(
        self, mock_run_coro: Mock, mock_get_loop: Mock, mock_get_sandbox: Mock
    ) -> None:
        """Test catch_stdio with basic function."""
        # Setup mocks
        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop
        mock_get_sandbox.return_value = mock_loop

        mock_future = Mock()
        mock_future.result.return_value = {
            "result": 42,
            "stdout": "output",
            "stderr": "",
        }
        mock_run_coro.return_value = mock_future

        def test_func(x: int, y: int) -> int:
            return x + y

        test_queue: queue.Queue = queue.Queue()
        result = catch_stdio(test_queue, test_func, {"y": 2}, 1)

        assert result == {"result": 42, "stdout": "output", "stderr": ""}
        mock_run_coro.assert_called_once()

    @patch("pysandboxes.remote.catch_stdio.get_sandbox_loop")
    @patch("asyncio.get_event_loop")
    def test_catch_stdio_wrong_event_loop(
        self, mock_get_loop: Mock, mock_get_sandbox: Mock
    ) -> None:
        """Test catch_stdio assertion when not in sandbox loop."""
        mock_get_loop.return_value = Mock()
        mock_get_sandbox.return_value = Mock()  # Different mock

        def test_func() -> None:
            pass

        with pytest.raises(AssertionError, match="Should be in sandbox loop"):
            catch_stdio(None, test_func, {})


class TestACatchStdio:
    """Test cases for acatch_stdio function."""

    @patch("pysandboxes.remote.catch_stdio.get_sandbox_loop")
    @patch("asyncio.get_event_loop")
    @pytest.mark.asyncio
    async def test_acatch_stdio_sync_function(
        self, mock_get_loop: Mock, mock_get_sandbox: Mock
    ) -> None:
        """Test acatch_stdio with synchronous function."""
        # Setup mocks to pass assertion
        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop
        mock_get_sandbox.return_value = mock_loop

        def test_func(message: str) -> str:
            print(f"Output: {message}")
            return f"Result: {message}"

        # Mock sys.stdout and sys.stderr to avoid actual modification
        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            mock_stdout.set_context = Mock()
            mock_stderr.set_context = Mock()

            result = await acatch_stdio(None, test_func, {"message": "test"})

            # Should contain result key
            assert "result" in result
            assert result["result"] == "Result: test"
            assert "stdout" in result
            assert "stderr" in result

    @patch("pysandboxes.remote.catch_stdio.get_sandbox_loop")
    @patch("asyncio.get_event_loop")
    @pytest.mark.asyncio
    async def test_acatch_stdio_async_function(
        self, mock_get_loop: Mock, mock_get_sandbox: Mock
    ) -> None:
        """Test acatch_stdio with asynchronous function."""
        # Setup mocks
        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop
        mock_get_sandbox.return_value = mock_loop

        async def test_async_func(value: int) -> int:
            print(f"Async output: {value}")
            return value * 2

        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            mock_stdout.set_context = Mock()
            mock_stderr.set_context = Mock()

            result = await acatch_stdio(None, test_async_func, {"value": 21})

            assert "result" in result
            assert result["result"] == 42

    @patch("pysandboxes.remote.catch_stdio.get_sandbox_loop")
    @patch("asyncio.get_event_loop")
    @pytest.mark.asyncio
    async def test_acatch_stdio_function_exception(
        self, mock_get_loop: Mock, mock_get_sandbox: Mock
    ) -> None:
        """Test acatch_stdio when function raises exception."""
        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop
        mock_get_sandbox.return_value = mock_loop

        def test_func() -> None:
            raise ValueError("Test exception")

        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            mock_stdout.set_context = Mock()
            mock_stderr.set_context = Mock()

            result = await acatch_stdio(None, test_func, {})

            assert "exception" in result
            assert "result" not in result
            exception, traceback = result["exception"]
            assert isinstance(exception, ValueError)
            assert str(exception) == "Test exception"

    @patch("pysandboxes.remote.catch_stdio.get_sandbox_loop")
    @patch("asyncio.get_event_loop")
    @pytest.mark.asyncio
    async def test_acatch_stdio_with_sync_queue(
        self, mock_get_loop: Mock, mock_get_sandbox: Mock
    ) -> None:
        """Test acatch_stdio with synchronous queue."""
        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop
        mock_get_sandbox.return_value = mock_loop

        def test_func() -> str:
            return "queue_test"

        test_queue: queue.Queue = queue.Queue()

        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            mock_stdout.set_context = Mock()
            mock_stderr.set_context = Mock()

            result = await acatch_stdio(test_queue, test_func, {})

            assert result["result"] == "queue_test"
            # Queue should receive the result
            queue_result = test_queue.get_nowait()
            assert queue_result["result"] == "queue_test"

    @patch("pysandboxes.remote.catch_stdio.get_sandbox_loop")
    @patch("asyncio.get_event_loop")
    @pytest.mark.asyncio
    async def test_acatch_stdio_with_async_queue(
        self, mock_get_loop: Mock, mock_get_sandbox: Mock
    ) -> None:
        """Test acatch_stdio with asynchronous queue."""
        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop
        mock_get_sandbox.return_value = mock_loop

        def test_func() -> int:
            return 123

        test_queue: asyncio.Queue = asyncio.Queue()

        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            mock_stdout.set_context = Mock()
            mock_stderr.set_context = Mock()

            result = await acatch_stdio(test_queue, test_func, {})

            assert result["result"] == 123
            # Async queue should receive the result
            queue_result = test_queue.get_nowait()
            assert queue_result["result"] == 123
