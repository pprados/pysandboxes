import logging
from typing import Any, Callable, Dict, Optional

from ..all_rules import AllRules
from ..base_daemon import BaseDaemon
from ..sb_types import Envs
from ..tools import Environ, SyncOrAsyncFunc, set_is_in_sandbox

logger = logging.getLogger(__name__)


class NoneDaemon(BaseDaemon):
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
        init_fn: Optional[SyncOrAsyncFunc],
    ) -> None:
        self._is_started = True
        set_is_in_sandbox(True)  # Simulate the presence of sandbox

    async def _stop(self, max_pending: int) -> None:
        pass

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        set_is_in_sandbox(False)
        self._is_started = False

    def update_rules(
        self,
        *,
        envs: Envs,
        all_rules: "AllRules",
    ) -> "AllRules":
        return all_rules

    async def join(self) -> int:
        raise NotImplementedError

    async def async_call_in_sandbox(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        raise NotImplementedError

    def call_in_sandbox(
        self,
        func: Callable[..., Any],
        _force_incomming: bool,
        *args: Any,
        **kwargs: Dict[str, Any],
    ) -> Any:
        raise NotImplementedError
