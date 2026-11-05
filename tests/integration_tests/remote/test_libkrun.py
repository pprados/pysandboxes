# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Integration tests for the libkrun OS sandbox provider."""

import pytest
from pysandboxes.sandboxes_api import sandboxes


@pytest.mark.asyncio
async def test_libkrun_basic() -> None:
    from pysandboxes.remote.libkrun_sse_daemon import LibkrunSSEDaemon

    if LibkrunSSEDaemon.unavailable_reason():
        pytest.skip(f"libkrun not available: {LibkrunSSEDaemon.unavailable_reason()}")

    try:
        async with sandboxes(os_sandbox="libkrun"):
            pass
    except Exception as e:
        import glob

        for f in glob.glob("/tmp/tmp*/*.log"):
            print(f, open(f).read())
        raise e
        pass
