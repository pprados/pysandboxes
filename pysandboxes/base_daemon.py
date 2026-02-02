import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, TYPE_CHECKING

from .tools import SyncOrAsyncFunc
from .types import ConfigLines, Envs

if TYPE_CHECKING:
    from .py_sandbox import AllRules

logger = logging.getLogger(__name__)

_mixed_sync_and_async_error = ("Cannot call the synchronize sandbox function "
                               "from another sandbox async function")


class BaseDaemon(ABC):
    __slots__ = ('_is_started', '_token')  # TODO: partout __slots__

    def __init__(self, token: str):
        self._is_started = False
        self._token = token

    @abstractmethod
    def update_rules(self,
                     *,
                     envs: Envs,
                     all_rules: "AllRules",
                     ) -> "AllRules":
        raise NotImplementedError

    @property
    def is_started(self) -> bool:
        return self._is_started

    @abstractmethod
    async def start(self,
                    all_rules:"AllRules",
                    *,
                    log_level: int,
                    envs: Envs,
                    init_fn: Optional[SyncOrAsyncFunc],
                    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def shutdown(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def join(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def update_rules(self,
                     *,
                     envs: Envs,
                     config: ConfigLines) -> "AllRules":
        raise NotImplementedError

    @property
    def token(self) -> Optional[str]:
        return self._token

    @abstractmethod
    async def async_call_in_sandbox(self,
                                    func: Callable[..., Any],
                                    timeout: float,
                                    *args: Any,
                                    **kwargs: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def call_in_sandbox(self,
                        func: Callable[..., Any],
                        timeout: float,
                        *args: Any,
                        **kwargs: Any) -> Any:
        raise NotImplementedError
