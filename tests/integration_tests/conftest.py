from typing import Any

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_post_finalizer(fixturedef: Any, request: Any) -> None:
    from pysandboxes.private_loop import get_sandbox_loop

    loop = get_sandbox_loop()
    loop.stop()
    # Fix a problem with pycharm. It's call close() on a running loop
    if hasattr(loop, "_thread_id"):
        setattr(loop, "_thread_id", None)
