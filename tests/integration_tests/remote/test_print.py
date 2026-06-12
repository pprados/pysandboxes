# %% Test print
import _pytest  # type: ignore[import-untyped]
import pytest  # type: ignore[import-untyped]

from pysandboxes import sandboxes

from .._env import NO_PROFILE_DNS_REASON, profile_hosts_resolvable
from ..sample import (
    async_print_stdin_stdout,
    config_path,
    init_sandbox,
    sync_print_stdin_stdout,
)

pytestmark = pytest.mark.skipif(not profile_hosts_resolvable(), reason=NO_PROFILE_DNS_REASON)


def test_sync_catch_stdout_and_stderr(capsys: _pytest.capture.CaptureFixture) -> None:  # type: ignore[attr-defined]
    """
    Catch stdin and stdout from the sandbox, in the main process
    """
    with sandboxes(init_sandbox, sandboxes_config=config_path):
        sync_print_stdin_stdout()
        captured_output = capsys.readouterr()
        assert captured_output.out == "hello\n"
        assert captured_output.err == "world\n"


async def test_async_catch_stdout_and_stderr(
    capsys: _pytest.capture.CaptureFixture,  # type: ignore[attr-defined]
) -> None:
    """
    Catch stdin and stdout from the sandbox, in the main process
    """
    async with sandboxes(init_sandbox, sandboxes_config=config_path):
        await async_print_stdin_stdout()
        captured_output = capsys.readouterr()
        assert captured_output.out == "hello\n"
        assert captured_output.err == "world\n"
