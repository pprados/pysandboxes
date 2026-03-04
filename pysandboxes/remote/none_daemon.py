# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""No-operation daemon for testing and debugging.

This module provides a daemon implementation that doesn't actually create
a separate process, allowing code to run directly in the current process.
Useful for debugging and testing sandbox functionality.
"""

import logging
from typing import Any, Callable

from ..all_rules import AllRules
from ..base_daemon import BaseDaemon
from ..sb_types import Envs
from ..tools import Environ, SyncOrAsyncFunc, set_is_in_sandbox

logger = logging.getLogger(__name__)


class NoneDaemon(BaseDaemon):
    """No-operation daemon that runs code in the current process.

    This daemon implementation doesn't create a separate process, making it
    useful for debugging and testing without the complexity of IPC.
    """

    # def __init__(self,
    #              token:str,
    #              **kwargs):
    #     super().__init__(token,**kwargs)

    async def _start(
            self,
            all_rules: "AllRules",
            *,
            envs: Environ,
            log_level: int,
            init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Start the daemon by simulating sandbox environment.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables to use.
            log_level: Logging level to set.
            init_fn: Optional initialization function to call.
        """
        self._is_started = True
        set_is_in_sandbox(True)  # Simulate the presence of sandbox

    async def _stop(self, max_pending: int) -> None:
        """Stop the daemon.

        Args:
            max_pending: Maximum number of pending operations to wait for.
        """
        pass

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        """Shutdown the daemon and cleanup.

        Args:
            graceful_shutdown: Whether to perform graceful shutdown.
        """
        set_is_in_sandbox(False)
        self._is_started = False

    def update_rules(
            self,
            *,
            envs: Envs,
            all_rules: "AllRules",
    ) -> "AllRules":
        """Update security rules (no-op for none daemon).

        Args:
            envs: Environment variables.
            all_rules: Current security rules.

        Returns:
            The same rules unchanged.
        """
        return all_rules

    async def join(self) -> int:
        """Wait for daemon to complete.

        Returns:
            Exit code.

        Raises:
            NotImplementedError: Always raised as this is not supported.
        """
        raise NotImplementedError

    async def async_call_in_sandbox(
            self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Execute async function in sandbox.

        Args:
            func: Function to execute.
            args: Positional arguments.
            kwargs: Keyword arguments.

        Returns:
            Function result.

        Raises:
            NotImplementedError: Always raised as this is not supported.
        """
        raise NotImplementedError

    def call_in_sandbox(
            self,
            func: Callable[..., Any],
            _force_incomming: bool,
            *args: Any,
            **kwargs: dict[str, Any],
    ) -> Any:
        """Execute function in sandbox.

        Args:
            func: Function to execute.
            _force_incomming: Force incoming execution mode.
            args: Positional arguments.
            kwargs: Keyword arguments.

        Returns:
            Function result.

        Raises:
            NotImplementedError: Always raised as this is not supported.
        """
        raise NotImplementedError
