# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""``functools.wraps`` without the back-reference to the unguarded original.

``functools.update_wrapper`` always ends with ``wrapper.__wrapped__ = wrapped``,
outside ``assigned``, so a guard built with it hands its own original back by
name: ``open.__wrapped__("/etc/shadow")`` calls the real ``io.open``.

That is not a barrier worth much against code written to escape, which reaches
the same object through ``wrapper.__closure__[0].cell_contents`` or
``gc.get_referents``. It matters against what this layer is built for -- code a
model produced while solving the wrong problem, which, refused once on ``open``,
plausibly reaches for ``open.__wrapped__`` because unwrapping a decorator is a
common idiom, not a sandbox attack. See the design target in
``wiki/audit-python-security.md``.

``__signature__`` is restored explicitly because ``inspect.signature`` follows
``__wrapped__``: without it, dropping the attribute would silently change every
guarded callable's advertised signature, which the samples introspect.
"""

import functools
import inspect
from typing import Any, Callable


def guard_wraps(func: Callable[..., Any]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Like :func:`functools.wraps`, minus ``__wrapped__``."""

    def decorate(wrapper: Callable[..., Any]) -> Callable[..., Any]:
        functools.update_wrapper(wrapper, func)
        try:
            wrapper.__signature__ = inspect.signature(func)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            # A C builtin with no introspectable signature: nothing to restore.
            pass
        del wrapper.__wrapped__  # type: ignore[attr-defined]
        return wrapper

    return decorate
