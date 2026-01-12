from abc import ABC, abstractmethod
from typing import Any

from .tools import set_is_in_sandbox, is_in_sandbox


class BaseStartDaemon(ABC):
    async def start(self) -> Any:
        set_is_in_sandbox(True)
        await self._start()
        assert is_in_sandbox()  # FIXME: a garder ?

    @abstractmethod
    async def _start(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def close(self,id:Any) -> None:
        raise NotImplementedError

    @abstractmethod
    async def join(self) -> int:
        raise NotImplementedError

