import logging
from typing import Optional, Callable, Any

from .local_task_daemon import LocalTaskDaemon
from ..all_rules import AllRules
from ..base_daemon import BaseDaemon
from ..tools import SyncOrAsyncFunc, set_is_in_sandbox
from ..sb_types import Envs

logger = logging.getLogger(__name__)


class NoneDaemon(BaseDaemon):

    # def __init__(self,
    #              token:str,
    #              **kwargs):
    #     super().__init__(token,**kwargs)

    async def start(self,
                    all_rules:AllRules,
                    *,
                    log_level: int,
                    envs: Optional[Envs],
                    init_fn: Optional[SyncOrAsyncFunc],
                    ) -> None:
        self._is_started = True
        set_is_in_sandbox(True)  # Simulate the presence of sandbox

    async def shutdown(self) -> None:
        set_is_in_sandbox(False)
        self._is_started = False



    def update_rules(self,
                     *,
                     envs: Envs,
                     all_rules: "AllRules",
                     ) -> "AllRules":
        return all_rules


    async def join(self) -> int:
        raise NotImplementedError

    def update_rules(self,
                     *,
                     envs: Envs,
                     all_rules: "AllRules") -> "AllRules":
        return all_rules

    async def async_call_in_sandbox(self,
                                    func: Callable[..., Any],
                                    timeout: float,
                                    *args: Any,
                                    **kwargs: Any) -> Any:
        raise NotImplementedError

    def call_in_sandbox(self,
                        func: Callable[..., Any],
                        timeout: float,
                        *args: Any,
                        **kwargs: Any) -> Any:
        raise NotImplementedError
