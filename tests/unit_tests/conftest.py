import logging
from typing import Iterator

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
def activate_guard() -> Iterator[None]:
    # Create test files and symlinks
    # Runs without patch.
    init_log_level()
    _deactivate_all_rules()
    _activate_guard_import_for_tests()
    yield
    # Disarm on the way out too, not only on the way in: the last test of a run
    # otherwise leaves its rules armed, and pytest ends the session with an
    # `os.chdir` back to the root directory that no rule exposes, so a plain
    # `pytest <file>` finishes on a RuleFileNotFoundError traceback.
    _deactivate_all_rules()
