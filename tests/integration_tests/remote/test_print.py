# %% Test print
import _pytest

from pysandboxes import sandboxes

from ..sample import (
    async_print_stdin_stdout,
    config_path,
    init_sandbox,
    sync_print_stdin_stdout,
)


def test_sync_catch_stdout_and_stderr(capsys: _pytest.capture.CaptureFixture) -> None:
    """
    Catch stdin and stdout from the sandbox, in the main process
    """
    with sandboxes(init_sandbox, sandboxes_config=config_path):
        sync_print_stdin_stdout()
        captured_output = capsys.readouterr()
        assert captured_output.out == "hello\n"
        assert captured_output.err == "world\n"


async def test_async_catch_stdout_and_stderr(
    capsys: _pytest.capture.CaptureFixture,
) -> None:
    """
    Catch stdin and stdout from the sandbox, in the main process
    """
    async with sandboxes(init_sandbox, sandboxes_config=config_path):
        await async_print_stdin_stdout()
        captured_output = capsys.readouterr()
        assert captured_output.out == "hello\n"
        assert captured_output.err == "world\n"
