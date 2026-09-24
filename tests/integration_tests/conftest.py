import os
from typing import Any

import pytest  # type: ignore[import-untyped]

# In CI every integration test must run: a skip there means a provider or a network the
# runner lacks. The session still runs to the end, so the report shows what passes and
# what does not; only then does it fail, listing each skip with its reason.
_FAIL_ON_SKIP = "PYSANDBOXES_FAIL_ON_SKIP"
_skipped: list[str] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if os.environ.get(_FAIL_ON_SKIP) == "1" and report.skipped and not hasattr(report, "wasxfail"):
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        _skipped.append(f"{report.nodeid}: {reason.removeprefix('Skipped: ')}")


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if _skipped:
        terminalreporter.section(f"skipped tests fail the run ({_FAIL_ON_SKIP}=1)", red=True)
        for line in _skipped:
            terminalreporter.line(line)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _skipped and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_post_finalizer(fixturedef: Any, request: Any) -> None:
    from pysandboxes.private_loop import get_sandbox_loop

    loop = get_sandbox_loop()
    loop.stop()
    # Fix a problem with pycharm. It's call close() on a running loop
    if hasattr(loop, "_thread_id"):
        loop._thread_id = None  # type: ignore[attr-defined]
