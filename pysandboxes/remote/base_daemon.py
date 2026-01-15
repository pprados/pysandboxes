import logging
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING, Callable, Optional

from . import ConfigLines, Envs
from ..guard_sandbox import AllRules

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class BaseDaemon(ABC):
    def __init__(self, token: Optional[str] = None):
        self._is_started = False
        self._token = token

    @abstractmethod
    def update_rules(self,
                     *,
                     envs: Envs,
                     config: ConfigLines) -> AllRules:
        raise NotImplementedError

    @property
    def is_started(self) -> bool:
        return self._is_started

    @abstractmethod
    async def start(self, log_level: int,
                    envs: Envs,
                    config: ConfigLines,
                    token: str) -> None:
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
                     config: ConfigLines) -> AllRules:
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
