import logging
from typing import Iterator

import deal
import pytest  # type: ignore[import-untyped]

import pysandboxes._contracts  # noqa: F401  # its import disables deal: import it before enabling
from pysandboxes.guard_import import framework_imports

from .guard.test_guard_io import (
    _activate_guard_import_for_tests,
    _deactivate_all_rules,
)

deal.enable(warn=False)


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
    with framework_imports():
        _deactivate_all_rules()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    # A test that fails with the import guard still armed must be reported, not crash the session:
    # pytest imports its report formatting lazily, and the guard would refuse `_pytest`.
    with framework_imports():
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_exception_interact(
    node: pytest.Item, call: pytest.CallInfo[None], report: pytest.TestReport
) -> Iterator[None]:
    with framework_imports():
        yield


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # A teardown that failed leaves the guards armed, and pytest then ends on an `os.chdir` no rule exposes.
    with framework_imports():
        _deactivate_all_rules()
