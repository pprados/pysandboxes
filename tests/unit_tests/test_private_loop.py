"""Unit tests for private_loop module."""

import asyncio
import threading
from unittest.mock import Mock, call, patch

import pytest  # type: ignore[import-untyped]

import pysandboxes.private_loop as private_loop
from pysandboxes.private_loop import (
    _ensure_background_loop,
    _reset_sandbox_loop,
    get_sandbox_loop,
    purge_loop,
    sandbox_loop,
    set_sandbox_loop,
)


class TestEnsureBackgroundLoop:
    """Test cases for _ensure_background_loop function."""

    def test_ensure_background_loop_no_new_loop(self) -> None:
        """Test _ensure_background_loop returns None when new_loop is False
        and no loop exists."""
        with patch("pysandboxes.private_loop._background_loop_ref", None):
            result = _ensure_background_loop(new_loop=False)
            assert result is None

    @patch("asyncio.get_running_loop")
    def test_ensure_background_loop_in_coroutine(self, mock_get_running_loop: Mock) -> None:
        """Test _ensure_background_loop when already in a coroutine."""
        mock_loop = Mock()
        mock_loop.is_running.return_value = True
        mock_get_running_loop.return_value = mock_loop

        with patch("pysandboxes.private_loop._background_loop_ref", None):
            result = _ensure_background_loop(new_loop=True)

            assert result == mock_loop
            mock_get_running_loop.assert_called_once()

    def test_ensure_background_loop_runs_new_loop_on_background_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outside async code, requesting a loop starts its runner on a new thread."""
        monkeypatch.setattr(private_loop, "_background_loop_ref", None)
        monkeypatch.setattr(private_loop, "_new_event_loop", False)
        monkeypatch.setattr(private_loop, "_thread", None)
        loop = asyncio.new_event_loop()
        runner_thread_ids: list[int] = []
        monkeypatch.setattr(loop, "run_forever", lambda: runner_thread_ids.append(threading.get_ident()))
        monkeypatch.setattr(asyncio, "new_event_loop", lambda: loop)
        thread = None
        try:
            with patch("asyncio.get_running_loop", side_effect=RuntimeError("no running event loop")):
                result = _ensure_background_loop(new_loop=True)
            thread = private_loop._thread

            assert result is loop
            assert thread is not None
            thread.join(timeout=1)
            assert not thread.is_alive()
            assert runner_thread_ids == [thread.ident]
        finally:
            if thread is not None:
                thread.join(timeout=1)
            asyncio.set_event_loop(None)
            loop.close()


class TestSandboxLoopDecorator:
    """Test cases for sandbox_loop decorator."""

    def test_sandbox_loop_decorator_sync_function(self) -> None:
        """The decorator selects the sandbox loop when no loop is already running."""
        sandbox_event_loop = Mock()

        with (
            patch("pysandboxes.private_loop.get_sandbox_loop", return_value=sandbox_event_loop),
            patch("asyncio.get_running_loop", side_effect=RuntimeError("no running event loop")),
            patch("asyncio.set_event_loop") as set_event_loop,
        ):

            @sandbox_loop
            def test_func(x: int, y: int) -> int:
                return x + y

            result = test_func(1, 2)

        assert result == 3
        set_event_loop.assert_called_once_with(sandbox_event_loop)
        _reset_sandbox_loop()

    def test_sandbox_loop_decorator_restores_the_calling_loop(self) -> None:
        old_loop = Mock()
        sandbox_event_loop = Mock()

        with (
            patch("pysandboxes.private_loop.get_sandbox_loop", return_value=sandbox_event_loop),
            patch("asyncio.get_running_loop", return_value=old_loop),
            patch("asyncio.set_event_loop") as set_event_loop,
        ):

            @sandbox_loop
            def test_func() -> str:
                return "done"

            assert test_func() == "done"

        assert set_event_loop.call_args_list == [call(sandbox_event_loop), call(old_loop)]

    @pytest.mark.asyncio
    async def test_sandbox_loop_decorator_async_function(self) -> None:
        """Test sandbox_loop decorator on asynchronous function."""

        @sandbox_loop
        async def test_async_func(x: int, y: int) -> int:
            return x + y

        result = await test_async_func(1, 2)
        assert result == 3
        _reset_sandbox_loop()

    def test_sandbox_loop_decorator_preserves_function_attributes(self) -> None:
        """Test that sandbox_loop decorator preserves function attributes."""

        @sandbox_loop
        def test_func() -> str:
            """Test function docstring."""
            return "test"

        assert test_func.__name__ == "test_func"
        assert test_func.__doc__ and "Test function docstring" in test_func.__doc__
        _reset_sandbox_loop()


class TestResetSandboxLoop:
    """Test cases for _reset_sandbox_loop function."""

    def test_reset_sandbox_loop(self) -> None:
        """Test resetting the sandbox loop."""
        # Set a loop first
        loop = asyncio.new_event_loop()
        try:
            set_sandbox_loop(loop)

            # Reset the loop
            _reset_sandbox_loop()

            # After reset, should not have a loop reference
            with patch("pysandboxes.private_loop._background_loop_ref", None):
                result = _ensure_background_loop(new_loop=False)
                assert result is None
        finally:
            loop.close()

    def test_reset_sandbox_loop_multiple_calls(self) -> None:
        """Test that multiple calls to _reset_sandbox_loop don't cause issues."""
        _reset_sandbox_loop()
        _reset_sandbox_loop()

        assert _ensure_background_loop(new_loop=False) is None


class TestGetSandboxLoop:
    """Test cases for get_sandbox_loop function."""

    @patch("pysandboxes.private_loop._ensure_background_loop")
    def test_get_sandbox_loop_success(self, mock_ensure_loop: Mock) -> None:
        """Test successful get_sandbox_loop call."""
        mock_loop = Mock()
        mock_ensure_loop.return_value = mock_loop

        result = get_sandbox_loop()

        assert result == mock_loop
        mock_ensure_loop.assert_called_once_with(new_loop=True)

    @patch("pysandboxes.private_loop._ensure_background_loop")
    @patch("asyncio.get_running_loop")
    def test_get_sandbox_loop_none_returned(self, mock_get_running_loop: Mock, mock_ensure_loop: Mock) -> None:
        """Test get_sandbox_loop when _ensure_background_loop returns None."""
        mock_ensure_loop.return_value = None
        mock_fallback_loop = Mock()
        mock_get_running_loop.return_value = mock_fallback_loop

        result = get_sandbox_loop()

        assert result == mock_fallback_loop
        mock_ensure_loop.assert_called_once_with(new_loop=True)
        mock_get_running_loop.assert_called_once()

    @patch("pysandboxes.private_loop._ensure_background_loop")
    def test_get_sandbox_loop_exception_handling(self, mock_ensure_loop: Mock) -> None:
        """Test get_sandbox_loop handles exceptions from _ensure_background_loop."""
        mock_ensure_loop.side_effect = Exception("Test exception")

        with pytest.raises(Exception, match="Test exception"):
            get_sandbox_loop()


@pytest.mark.asyncio
async def test_purge_loop_cancels_pending_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(private_loop, "_background_loop_ref", loop)
    monkeypatch.setattr(private_loop, "_new_event_loop", True)
    task = asyncio.create_task(asyncio.Event().wait())
    await asyncio.sleep(0)

    assert await purge_loop() is loop
    assert task.cancelled()
    assert private_loop._background_loop_ref is None


@pytest.mark.asyncio
async def test_purge_loop_leaves_a_shared_loop_running(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(private_loop, "_background_loop_ref", loop)
    monkeypatch.setattr(private_loop, "_new_event_loop", False)
    task = asyncio.create_task(asyncio.Event().wait())
    await asyncio.sleep(0)

    assert await purge_loop() is None
    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
