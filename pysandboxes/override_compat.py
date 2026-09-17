# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Compatibility shim for typing.override (Python 3.12+) in environments without typing_extensions.

Used when running inside a QEMU guest or other environment with older Python
and no typing_extensions installed. The no-op fallback allows the daemon to load.
"""

from collections.abc import Callable
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])

# Prefer typing_extensions first so Pyright and Python < 3.12 resolve `override`
# without relying on typing.override (3.12+). Fall back to stdlib, then no-op for
# minimal guests (e.g. QEMU) with neither package installed.
try:
    from typing_extensions import override
except ImportError:
    try:
        from typing import override  # type: ignore[attr-defined,no-redef]
    except ImportError:

        def override(__func: _F, /) -> _F:
            return __func


__all__ = ("override",)
