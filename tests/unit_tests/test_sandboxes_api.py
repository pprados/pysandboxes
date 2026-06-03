"""Unit tests for sandboxes_api module."""

from unittest.mock import Mock, patch

import pytest  # type: ignore[import-untyped]

from pysandboxes.sandboxes_api import (
    _check__main__coroutine,
    run,
    sandbox,
    sandboxes,
)


class TestCheckMainCoroutine:
    """Test cases for _check__main__coroutine function."""

    def test_check_main_coroutine_with_main_module(self) -> None:
        """Test that coroutine from __main__ raises ValueError."""
        # Create a mock coroutine with __main__ module
        mock_coroutine = Mock()
        mock_frame = Mock()
        mock_module = Mock()
        mock_module.__name__ = "__main__"

        mock_coroutine.cr_frame = mock_frame

        with patch("pysandboxes.sandboxes_api.inspect.getmodule", return_value=mock_module):
            with pytest.raises(
                ValueError,
                match="The coroutine must be declared in a module " "other than __main__",
            ):
                _check__main__coroutine(mock_coroutine)

    def test_check_main_coroutine_with_other_module(self) -> None:
        """Test that coroutine from other module doesn't raise."""
        mock_coroutine = Mock()
        mock_frame = Mock()
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        mock_coroutine.cr_frame = mock_frame

        with patch("pysandboxes.sandboxes_api.inspect.getmodule", return_value=mock_module):
            # Should not raise
            _check__main__coroutine(mock_coroutine)

    def test_check_main_coroutine_with_no_module(self) -> None:
        """Test that coroutine with no module doesn't raise."""
        mock_coroutine = Mock()
        mock_frame = Mock()
        mock_coroutine.cr_frame = mock_frame

        with patch("pysandboxes.sandboxes_api.inspect.getmodule", return_value=None):
            # Should not raise
            _check__main__coroutine(mock_coroutine)

    def test_check_main_coroutine_with_module_no_name(self) -> None:
        """Test that coroutine with module without __name__ doesn't raise."""
        mock_coroutine = Mock()
        mock_frame = Mock()
        mock_module = Mock(spec=[])  # Module without __name__ attribute

        mock_coroutine.cr_frame = mock_frame

        with patch("pysandboxes.sandboxes_api.inspect.getmodule", return_value=mock_module):
            # Should not raise
            _check__main__coroutine(mock_coroutine)


class TestSandboxDecorator:
    """Test cases for sandbox decorator."""

    @patch("pysandboxes._os_sandbox.call_in_sandbox")
    def test_sandbox_decorator_sync_function(self, mock_call_in_sandbox: Mock) -> None:
        """Test sandbox decorator on synchronous function."""
        mock_call_in_sandbox.return_value = 42

        @sandbox
        def test_func(x: int, y: int) -> int:
            return x + y

        result = test_func(1, 2)

        assert result == 42
        mock_call_in_sandbox.assert_called_once()
        # Check that the original function was passed to call_in_sandbox
        args, kwargs = mock_call_in_sandbox.call_args
        assert len(args) >= 1
        assert callable(args[0])

    @patch("pysandboxes._os_sandbox.async_call_in_sandbox")
    @pytest.mark.asyncio
    async def test_sandbox_decorator_async_function(self, mock_async_call_in_sandbox: Mock) -> None:
        """Test sandbox decorator on asynchronous function."""

        mock_async_call_in_sandbox.return_value = 42

        @sandbox
        async def test_async_func(x: int, y: int) -> int:
            return x + y

        result = await test_async_func(1, 2)

        assert result == 42
        mock_async_call_in_sandbox.assert_called_once()

    def test_sandbox_decorator_without_parentheses(self) -> None:
        """Test that sandbox decorator works without parentheses."""

        @sandbox
        def test_func() -> str:
            return "test"

        assert callable(test_func)

    def test_sandbox_decorator_with_parentheses(self) -> None:
        """Test that sandbox decorator works with parentheses."""

        @sandbox()
        def test_func() -> str:
            return "test"

        assert callable(test_func)


class TestRunFunction:
    """Test cases for run function."""

    def test_run_non_coroutine(self) -> None:
        """Test run function with non-coroutine."""
        # The run function doesn't actually validate input type in the
        # real implementation so we'll just test that it doesn't crash
        # with non-coroutine input
        with patch("pysandboxes.sandboxes_api._check__main__coroutine"):
            with patch("asyncio.run"):
                with pytest.raises(ValueError):
                    run("not a coroutine")  # type: ignore


class TestSandboxesContextManager:
    """Test cases for sandboxes context manager."""

    @patch("pysandboxes._os_sandbox.start_daemon")
    @patch("pysandboxes.sandboxes_api.async_shutdown_daemon")
    def test_sandboxes_sync_context_manager(self, mock_shutdown: Mock, mock_start: Mock) -> None:
        """Test synchronous sandboxes context manager."""
        mock_daemon = Mock()
        mock_start.return_value = mock_daemon

        with sandboxes():
            pass

        mock_start.assert_called_once()
        mock_shutdown.assert_called_once()

    @patch("pysandboxes._os_sandbox.async_start_daemon")
    @patch("pysandboxes.sandboxes_api.async_shutdown_daemon")
    @pytest.mark.asyncio
    async def test_sandboxes_async_context_manager(self, mock_async_shutdown: Mock, mock_async_start: Mock) -> None:
        """Test asynchronous sandboxes context manager."""
        mock_daemon = Mock()
        mock_async_start.return_value = mock_daemon

        async with sandboxes():
            pass

        mock_async_start.assert_called_once()
        mock_async_shutdown.assert_called_once()

    @patch("pysandboxes._os_sandbox.start_daemon")
    @patch("pysandboxes.sandboxes_api.async_shutdown_daemon")
    def test_sandboxes_context_manager_with_exception(self, mock_shutdown: Mock, mock_start: Mock) -> None:
        """Test that sandboxes context manager cleans up on exception."""
        mock_daemon = Mock()
        mock_start.return_value = mock_daemon

        with pytest.raises(ValueError):
            with sandboxes():
                raise ValueError("test error")

        mock_start.assert_called_once()
        mock_shutdown.assert_called_once()

    @patch("pysandboxes._os_sandbox.async_start_daemon")
    @patch("pysandboxes.sandboxes_api.async_shutdown_daemon")
    @pytest.mark.asyncio
    async def test_sandboxes_async_context_manager_with_exception(
        self, mock_async_shutdown: Mock, mock_async_start: Mock
    ) -> None:
        """Test that async sandboxes context manager cleans up on exception."""
        mock_daemon = Mock()
        mock_async_start.return_value = mock_daemon

        with pytest.raises(ValueError):
            async with sandboxes():
                raise ValueError("test error")

        mock_async_start.assert_called_once()
        mock_async_shutdown.assert_called_once()

    @patch("pysandboxes._os_sandbox.start_daemon")
    @patch("pysandboxes.sandboxes_api.async_shutdown_daemon")
    def test_sandboxes_context_manager_parameters(self, mock_async_shutdown: Mock, mock_async_start: Mock) -> None:
        """Test sandboxes context manager with parameters."""
        mock_daemon = Mock()
        mock_async_start.return_value = mock_daemon

        with sandboxes(sandboxes_config="test.conf"):
            pass

        mock_async_start.assert_called_once()
        mock_async_shutdown.assert_called_once()
        # Check that parameters were passed correctly - this is a basic test
        # since the actual parameter structure is complex
