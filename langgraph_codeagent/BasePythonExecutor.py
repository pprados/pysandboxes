from abc import abstractmethod
from typing import Any, Callable, Optional


class BasePythonExecutor:
    @abstractmethod
    def call(self,
             code_action: str,
             tools: dict[str, Callable],
             timeout: Optional[int] = None) -> tuple[Any, str, bool]:
        pass

    @abstractmethod
    async def acall(self,
                    code_action: str,
                    tools: dict[str, Callable],
                    timeout: Optional[int] = None) -> tuple[Any, str, bool]:
        pass
