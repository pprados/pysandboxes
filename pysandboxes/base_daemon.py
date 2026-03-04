# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Abstract base class for sandbox daemon implementations.

This module defines the base interface that all sandbox daemon providers
must implement. It provides common functionality for daemon lifecycle
management, configuration handling, and inter-process communication.
"""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable

from .immutable_dict import ImmutableDict
from .main_logger import ErrorMsg
from .sb_types import Envs, ConfigLines
from .tools import Environ, SyncOrAsyncFunc

if TYPE_CHECKING:
    from .all_rules import AllRules

logger = logging.getLogger(__name__)

_mixed_sync_and_async_error = (
    "Cannot call the synchronize sandbox function "
    "from another sandbox async function"
)


class BaseDaemon(ABC):
    """Abstract base class for all sandbox daemon implementations.

    This class defines the interface that all sandbox providers (subprocess,
    firejail, etc.) must implement for daemon lifecycle management.
    """

    __slots__ = ("_is_started", "_token", "_accept_incoming")

    def __init__(
            self,
            token: str,
            **kwargs: dict[str, Any],
    ) -> None:
        """Initialize the daemon with a unique token.

        Args:
            token: Unique identifier for this daemon instance.
            **kwargs: Additional provider-specific arguments.
        """
        self._is_started = False
        self._token = token
        self._accept_incoming = False

    def parse_rules(self,
                    rules: ConfigLines,
                    errors: list[ErrorMsg],
                    ) -> tuple[ImmutableDict[str, Any],ConfigLines]:
        return ImmutableDict({}),rules

    @abstractmethod
    def update_rules(
            self,
            *,
            envs: Envs,
            all_rules: "AllRules",
    ) -> "AllRules":
        """Some os-sandbox can update the rules (remove some duplicate rules)

        Returns:
            The modified all rules.
        """
        raise NotImplementedError

    @property
    def is_started(self) -> bool:
        """Check if the daemon is started.

        Returns:
            True if daemon is started, False otherwise.
        """
        return self._is_started

    @abstractmethod
    async def _start(
            self,
            all_rules: "AllRules",
            *,
            envs: Environ,
            log_level: int,
            init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Must be called via async_start_daemon().

        Args:
            all_rules: Sandbox configuration and rules.
            envs: Environment variables for the daemon.
            log_level: Logging level.
            init_fn: Optional initialization function.
        """
        raise NotImplementedError

    @abstractmethod
    async def _stop(self, max_pending: int) -> None:
        """Stop the daemon process.

        Args:
            max_pending: Maximum number of pending requests to wait for.
        """
        raise NotImplementedError

    @abstractmethod
    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        """Must be called via async_shutdown_daemon().

        Args:
            graceful_shutdown: Whether to shutdown gracefully.
        """
        self._accept_incoming = False

    @property
    def token(self) -> str:
        """Get the daemon's unique token.

        Returns:
            The daemon's unique identifier.
        """
        return self._token

    @abstractmethod
    async def async_call_in_sandbox(
            self,
            func: Callable[..., Any],
            _force_incomming: bool,
            *args: Any,
            **kwargs: Any,
    ) -> Any:
        """Async call a function in the sandbox

        Args:
            func: The function to call in the sandbox
            _force_incomming: Special flag to execute the function
            if the flag _accept_incomming is false (for call the last shutdown command)
            args: all argument for the function
            kwargs: all key-arguments for the function
        Returns:
            The return value
         Raises::
            Exception from the function
        """
        raise NotImplementedError

    @abstractmethod
    def call_in_sandbox(
            self,
            func: Callable[..., Any],
            _force_incomming: bool,
            *args: Any,
            **kwargs: dict[str, Any],
    ) -> Any:
        """Sync call a function in the sandbox

        Args:
            func: The function to call in the sandbox
            _force_incomming: Special flag to execute the function
            if the flag _accept_incomming is false (for call the last shutdown command)
            args: all argument for the function
            kwargs: all key-arguments for the function
        Returns:
            The return value
         Raises::
            Exception from the function
        """
        raise NotImplementedError


class FakeDaemon(BaseDaemon):
    def update_rules(
            self,
            *,
            envs: Envs,
            all_rules: "AllRules",
    ) -> "AllRules":
        return all_rules

    is_started = True

    async def _start(
            self,
            all_rules: "AllRules",
            *,
            envs: Environ,
            log_level: int,
            init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        logger.debug("FakeDaemon._start...")
        self._is_started = True

    async def _stop(self, max_pending: int) -> None:
        logger.debug("FakeDaemon._stop...")
        self._is_started = False

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        logger.debug("FakeDaemon._shutdown...")
        self._is_started = False

    async def async_call_in_sandbox(
            self,
            func: Callable[..., Any],
            _force_incomming: bool,
            *args: Any,
            **kwargs: Any,
    ) -> Any:
        raise NotImplemented("It's a Fake daemon, because you use `python-sb`.")

    def call_in_sandbox(
            self,
            func: Callable[..., Any],
            _force_incomming: bool,
            *args: Any,
            **kwargs: dict[str, Any],
    ) -> Any:
        raise NotImplemented("It's a Fake daemon, because you use `python-sb`.")
