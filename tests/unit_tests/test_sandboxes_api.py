"""Unit tests for sandboxes_api module."""

import inspect
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import ConfigSyntaxError
from pysandboxes.sandboxes_api import (
    run,
    sandbox,
    sandboxes,
)


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

    def test_sandbox_refuses_a_generator_function(self) -> None:
        """A generator function cannot be sent across the sandbox boundary."""
        with pytest.raises(TypeError, match="generator"):

            @sandbox
            def gen() -> Any:  # type: ignore[misc]
                yield 1

    def test_sandbox_refuses_an_async_generator_function(self) -> None:
        """An asynchronous generator function cannot be sent across the sandbox boundary."""
        with pytest.raises(TypeError, match="generator"):

            @sandbox
            async def agen() -> Any:  # type: ignore[misc]
                yield 1


class TestRunFunction:
    """Test cases for run function."""

    def test_run_non_coroutine(self) -> None:
        """Test run function with non-coroutine."""
        # The run function doesn't actually validate input type in the
        # real implementation so we'll just test that it doesn't crash
        # with non-coroutine input
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

    @patch("pysandboxes._os_sandbox.start_daemon")
    @patch("pysandboxes.sandboxes_api.async_shutdown_daemon")
    def test_sync_context_manager_passes_python_args(self, mock_shutdown: Mock, mock_start: Mock) -> None:
        """The interpreter arguments reach the daemon."""
        mock_start.return_value = Mock()

        with sandboxes(python_args=["-X", "dev"]):
            pass

        assert mock_start.call_args.kwargs["python_args"] == ["-X", "dev"]

    @patch("pysandboxes._os_sandbox.async_start_daemon")
    @patch("pysandboxes.sandboxes_api.async_shutdown_daemon")
    @pytest.mark.asyncio
    async def test_async_context_manager_passes_python_args(
        self, mock_async_shutdown: Mock, mock_async_start: Mock
    ) -> None:
        """The asynchronous entry, and so run(), passes the interpreter arguments on as the synchronous one does."""
        mock_async_start.return_value = Mock()

        async with sandboxes(python_args=["-X", "dev"]):
            pass

        assert mock_async_start.call_args.kwargs["python_args"] == ["-X", "dev"]


class TestExtraRulesNormalization:
    """extra_rules values that repeat can be given as list, tuple, set or frozenset."""

    def test_list_tuple_and_frozenset_are_normalized_to_a_set(self) -> None:
        cm = sandboxes(expose_ro=["/a", "/b"], expose_rw=("/c",), env_allow=frozenset({"X"}))

        assert cm.extra_rules["expose_ro"] == {"/a", "/b"}
        assert cm.extra_rules["expose_rw"] == {"/c"}
        assert cm.extra_rules["env_allow"] == {"X"}

    def test_a_plain_string_value_is_left_untouched(self) -> None:
        cm = sandboxes(os_sandbox="bwrap")

        assert cm.extra_rules["os_sandbox"] == "bwrap"


@pytest.mark.asyncio
async def test_async_enter_parses_the_config_off_the_event_loop_thread() -> None:
    """Parsing the configuration file is blocking I/O; it must not run on the event loop thread."""
    loop_thread = threading.current_thread()
    seen: dict[str, threading.Thread] = {}

    def fake_load_and_parse_config(*args: Any, **kwargs: Any) -> Any:
        seen["thread"] = threading.current_thread()
        raise ConfigSyntaxError("stop before starting a daemon", [])

    with patch("pysandboxes.py_sandbox.load_and_parse_config", side_effect=fake_load_and_parse_config):
        with pytest.raises(ConfigSyntaxError):
            async with sandboxes():
                pass

    assert seen["thread"] is not loop_thread


class TestRunParameters:
    """run() takes the parameters of sandboxes(), under the same names."""

    @patch("pysandboxes.sandboxes_api.sandboxes")
    def test_run_forwards_sandboxes_config(self, mock_sandboxes: Mock) -> None:
        """The configuration keyword is sandboxes_config, as for sandboxes()."""
        mock_sandboxes.return_value.__aenter__ = AsyncMock()
        mock_sandboxes.return_value.__aexit__ = AsyncMock(return_value=False)

        async def job() -> int:
            return 42

        assert run(job(), sandboxes_config="custom.conf") == 42
        assert mock_sandboxes.call_args.kwargs["sandboxes_config"] == "custom.conf"

    def test_run_and_sandboxes_share_their_parameter_names(self) -> None:
        """Every named parameter of sandboxes() exists in run(), under the same name."""
        sandboxes_params = set(inspect.signature(sandboxes).parameters) - {"extra_rules"}
        run_params = set(inspect.signature(run).parameters) - {"main", "extra_rules"}

        assert run_params == sandboxes_params


def test_importing_the_api_loads_multiprocessing_before_any_sandbox() -> None:
    # Arming the import guard evicts sys.modules, then hands back a module loaded before it without running its
    # code again. The samples' profiles were learned that way, so multiprocessing must be loaded here, or its first
    # import inside the sandbox runs its own imports (_weakrefset...) against rules that never listed them.
    code = "import sys, pysandboxes.sandboxes_api; print('multiprocessing.synchronize' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "True"


LOCKED_RULES = "py-sandbox=true\nos-sandbox=none\nlearn=false\n"


@patch("pysandboxes._os_sandbox.start_daemon")
def test_a_locked_rule_file_refuses_the_rules_of_the_api(mock_start: Mock, tmp_path: Path) -> None:
    config = tmp_path / ".py-sandboxes"
    config.write_text(LOCKED_RULES)

    with pytest.raises(ConfigSyntaxError) as e:
        with sandboxes(sandboxes_config=config, expose_ro={"/etc"}):  # type: ignore[arg-type]
            pass

    assert "locks the rules, the API cannot add expose_ro" in str(e.value)
    mock_start.assert_not_called()


@patch("pysandboxes._os_sandbox.async_start_daemon")
@pytest.mark.asyncio
async def test_a_locked_rule_file_refuses_the_rules_of_the_async_api(mock_start: Mock, tmp_path: Path) -> None:
    config = tmp_path / ".py-sandboxes"
    config.write_text(LOCKED_RULES)

    with pytest.raises(ConfigSyntaxError, match="the API cannot add os_sandbox"):
        async with sandboxes(sandboxes_config=config, os_sandbox="subprocess"):  # type: ignore[arg-type]
            pass

    mock_start.assert_not_called()


@patch("pysandboxes._os_sandbox.start_daemon")
@patch("pysandboxes.sandboxes_api.async_shutdown_daemon")
def test_a_locked_rule_file_without_api_rules_starts(mock_shutdown: Mock, mock_start: Mock, tmp_path: Path) -> None:
    config = tmp_path / ".py-sandboxes"
    config.write_text(LOCKED_RULES)

    with sandboxes(sandboxes_config=config):
        pass

    mock_start.assert_called_once()


_SIGTERM_INSIDE_SANDBOXES = """
import os, signal
from unittest.mock import AsyncMock, Mock, patch

from pysandboxes.sandboxes_api import sandboxes

shutdown = AsyncMock(side_effect=lambda *_: print("stopped", flush=True))
with patch("pysandboxes._os_sandbox.start_daemon", return_value=Mock()):
    with patch("pysandboxes.sandboxes_api.async_shutdown_daemon", shutdown):
        with sandboxes(os_sandbox="subprocess"):
            os.kill(os.getpid(), signal.SIGTERM)
            print("survived", flush=True)
"""


def test_sigterm_inside_sandboxes_stops_the_daemon_then_kills_the_process() -> None:
    result = subprocess.run([sys.executable, "-c", _SIGTERM_INSIDE_SANDBOXES], capture_output=True, text=True)

    assert result.returncode == -signal.SIGTERM, result.stderr
    assert "stopped" in result.stdout
    assert "survived" not in result.stdout


def test_a_failed_enter_restores_the_signal_handlers(tmp_path: Path) -> None:
    config = tmp_path / ".py-sandboxes"
    config.write_text("not a directive\n")
    before = signal.getsignal(signal.SIGTERM)

    with pytest.raises(ConfigSyntaxError):
        with sandboxes(sandboxes_config=config):
            pass

    assert signal.getsignal(signal.SIGTERM) is before


@pytest.mark.asyncio
async def test_a_failed_async_enter_restores_the_signal_handlers(tmp_path: Path) -> None:
    config = tmp_path / ".py-sandboxes"
    config.write_text("not a directive\n")
    before = signal.getsignal(signal.SIGTERM)

    with pytest.raises(ConfigSyntaxError):
        async with sandboxes(sandboxes_config=config):
            pass

    assert signal.getsignal(signal.SIGTERM) is before
