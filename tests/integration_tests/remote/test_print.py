# %% Test print
import _pytest

from integration_tests.sample import async_print_stdin_stdout, init_sandbox, \
    sync_print_stdin_stdout, config_path
from pysandboxes.sandboxes import sandboxes


def test_sync_catch_stdout_and_stderr(capsys: _pytest.capture.CaptureFixture):
    """
    Catch stdin and stdout from the sandbox, in the main process
    """
    with sandboxes(init_sandbox, config_path=config_path):
        sync_print_stdin_stdout()
        captured_output = capsys.readouterr()
        assert captured_output.out == "hello\n"
        assert captured_output.err == "world\n"


async def test_async_catch_stdout_and_stderr(capsys: _pytest.capture.CaptureFixture):
    """
    Catch stdin and stdout from the sandbox, in the main process
    """
    async with sandboxes(init_sandbox, config_path=config_path):
        await async_print_stdin_stdout()
        captured_output = capsys.readouterr()
        assert captured_output.out == "hello\n"
        assert captured_output.err == "world\n"

