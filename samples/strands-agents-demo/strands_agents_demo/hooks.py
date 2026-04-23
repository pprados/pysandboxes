"""Agent hooks (iteration cap)."""

from strands.hooks import BeforeInvocationEvent, BeforeModelCallEvent, HookProvider
from strands.hooks.registry import HookRegistry


class MaxModelCallsHook(HookProvider):
    """Raise if the model is invoked more than ``max_model_calls`` times per agent request."""

    def __init__(self, max_model_calls: int) -> None:
        self._max = max_model_calls
        self._count = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: object) -> None:
        registry.add_callback(BeforeInvocationEvent, self._on_invocation_start)
        registry.add_callback(BeforeModelCallEvent, self._before_model)

    def _on_invocation_start(self, event: BeforeInvocationEvent) -> None:
        self._count = 0

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        self._count += 1
        if self._count > self._max:
            raise RuntimeError(
                f"Exceeded max_model_calls ({self._max}); increase --max-iterations or simplify the task."
            )
