import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict

from .tools import set_is_in_sandbox, is_in_sandbox

logger = logging.getLogger(__name__)

class BaseDaemon(ABC):
    def __init__(self):
        self._is_started=False

    @property
    def is_started(self) -> bool:
        return self._is_started

    @abstractmethod
    async def start(self, log_level:int) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def shutdown(self, id:Any) -> None:
        raise NotImplementedError

    @abstractmethod
    async def join(self) -> None:
        raise NotImplementedError


