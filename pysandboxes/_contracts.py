# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Design-by-contract decorators, backed by `deal` when it is installed.

Contracts are off unless a test suite turns them on with `deal.enable()`. Without `deal` every decorator is the
identity, so the framework keeps no runtime dependency on it.

Only `pre`, `post`, `ensure`, `raises` and `inv` are exposed. `deal.has` swaps `socket.socket` and `sys.stdout` around
each call and `deal.activate` replaces the path finder in `sys.meta_path`: both fight the guards. A contract must
not decorate a function a guard installs in place of a stdlib one (the wrapper brings a `__wrapped__`), nor one that
reads the call stack at a fixed depth (the wrapper adds a frame).
"""

from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

try:
    import deal

    deal.disable(warn=False)
    HAS_DEAL = True
    pre = deal.pre
    post = deal.post
    ensure = deal.ensure
    inv = deal.inv
    raises = deal.raises
except ImportError:  # pragma: no cover
    HAS_DEAL = False

    def _noop(*_args: Any, **_kwargs: Any) -> Callable[[F], F]:
        return lambda func: func

    pre = post = ensure = inv = raises = _noop
