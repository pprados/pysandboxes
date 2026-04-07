# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Compatibility shim for typing.override (Python 3.12+) in environments without typing_extensions.

Used when running inside a QEMU guest or other environment with older Python
and no typing_extensions installed. The no-op fallback allows the daemon to load.
"""

try:
    from typing import override  # type: ignore[attr-defined]
except ImportError:
    try:
        from typing_extensions import override
    except ImportError:

        def override(f):
            return f
