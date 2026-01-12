import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict

from .tools import set_is_in_sandbox, is_in_sandbox

logger = logging.getLogger(__name__)

class BaseStartDaemon(ABC):
    async def start(self, log_level:int) -> Any:
        set_is_in_sandbox(True)
        await self._start(dict(os.environ),log_level)  # FIXME: gerer les envs
        assert is_in_sandbox()  # FIXME: a garder ?

    @abstractmethod
    async def _start(self,envs:Dict[str,str], log_level) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def close(self,id:Any) -> None:
        raise NotImplementedError

    @abstractmethod
    async def join(self) -> int:
        raise NotImplementedError


