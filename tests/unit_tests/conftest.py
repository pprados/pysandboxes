import logging

import pytest  # type: ignore[import-untyped]

from .guard.test_guard_io import (
    _activate_guard_import_for_tests,
    _deactivate_all_rules,
)


def init_log_level() -> None:
    sandboxes_level = logging.DEBUG
    uvicorn_level = logging.WARNING
    format = "[%(process)d] %(levelname)-5s %(name)s %(message)s"
    logging.basicConfig(level=min(sandboxes_level, logging.INFO), format=format)

    logging.getLogger("asyncio").setLevel(uvicorn_level)
    logging.getLogger("uvicorn").setLevel(uvicorn_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_level)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandboxes_level)


@pytest.fixture(autouse=True)
def activate_guard() -> None:
    # Create test files and symlinks
    # It's executer without patch.
    init_log_level()
    _deactivate_all_rules()
    _activate_guard_import_for_tests()
