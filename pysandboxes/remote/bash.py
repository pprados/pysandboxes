import argparse
import asyncio
import errno  # For specific error handling like EIO
import logging
import os
import pty
import sys
import tty

import dotenv
import termios

from pysandboxes.remote.os_sandbox import DEFAULT_OS_SANDBOX
from pysandboxes.remote.subprocess_daemon import BaseSubProcessDaemon
from pysandboxes.remote.tools import configure_logging_level

logger = logging.getLogger(__name__)


async def run_bash_in_pty(*args, **kwargs) -> None:
    """
    Launches a bash subprocess within a pseudo-terminal (PTY)
    and propagates parent's stdin/stdout/stderr to/from the PTY.
    Handles cases where the parent's stdin is not a terminal.
    """
    logger.debug("Parent: Starting - Creating a pseudo-terminal for bash.")

    # Create a master/slave pair of pseudo-terminal devices
    master_fd: int
    slave_fd: int
    master_fd, slave_fd = pty.openpty()

    old_settings: list[int] | None = None
    is_stdin_a_tty: bool = False

    # 1. Check if the parent's standard input is an actual terminal
    if sys.stdin.isatty():
        is_stdin_a_tty = True
        logger.debug("sys.stdin is a TTY. Attempting to set raw mode.")
        try:
            # Save current terminal settings to restore them later
            old_settings = termios.tcgetattr(sys.stdin.fileno())
            # Set the terminal to raw mode: no line buffering, no local echo
            tty.setraw(sys.stdin.fileno())
        except termios.error as e:
            logger.debug(f"Warning - Could not set raw mode for sys.stdin: {e}")
            is_stdin_a_tty = False  # Failed to set raw mode, treat as non-tty
        except Exception as e:
            logger.debug(f"Unexpected error while setting raw mode: {e}")
            is_stdin_a_tty = False
    else:
        logger.debug("sys.stdin is NOT a TTY (likely a pipe or file).")
        # No need to set raw mode; we will read in chunks.

    try:
        # Launch bash subprocess
        # -i: interactive mode
        # start_new_session=True: important for interactive shells
        # stdin/stdout/stderr: point to the slave end of the PTY
        # pass_fds: essential to pass the slave_fd to the child process
        process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            *args,
            # '/bin/bash', '-i',  # Interactive mode
            # '/bin/bash', '-i', #'-c', 'ls', # Interactive mode
            **kwargs,
            start_new_session=True,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            pass_fds=[slave_fd]
        )

        # Close the slave file descriptor in the parent process; it's now used by the child
        os.close(slave_fd)

        # --- Asynchronous tasks for communication via the PTY master ---

        async def read_parent_input_and_write_to_pty(fd_master: int) -> None:
            """
            Reads input from the parent (either char-by-char in raw mode
            or in chunks) and writes it to the PTY master.
            """
            if is_stdin_a_tty:
                logger.debug(
                    "Reading stdin (TTY) character by character for PTY.\r")
                # Read character by character in raw mode
                while True:
                    try:
                        # Use to_thread to run blocking os.read in a separate thread
                        char_bytes: bytes = await asyncio.to_thread(
                            sys.stdin.buffer.read, 1)
                        if not char_bytes:  # EOF (Ctrl+D) reached
                            logger.debug("(tty): EOF from stdin reached.\r")
                            break
                        # Write directly to the master file descriptor
                        os.write(fd_master, char_bytes)
                    except OSError as e:
                        if e.errno == errno.EIO:
                            # EIO is common when the PTY master is closed
                            logger.debug(
                                "(tty): EIO error, PTY master likely closed.\r")
                            break
                        logger.debug(
                            f"(tty): Error reading/writing on parent stdin: {e}\r")
                        break
                    except Exception as e:
                        logger.debug(
                            f"(tty): Unexpected error during stdin read: {e}\r")
                        break
            else:
                logger.debug("Reading stdin (non-TTY) in chunks for PTY.\r")
                # Read in chunks if sys.stdin is not a tty
                CHUNK_SIZE: int = 4096
                while True:
                    try:
                        # Use to_thread to run blocking os.read in a separate thread
                        chunk: bytes = await asyncio.to_thread(sys.stdin.buffer.read,
                                                               CHUNK_SIZE)
                        if not chunk:  # EOF reached
                            logger.debug("(non-tty): EOF from stdin reached.\r")
                            break
                        os.write(fd_master, chunk)
                    except OSError as e:
                        if e.errno == errno.EIO:
                            logger.debug(
                                "(non-tty): EIO error, PTY master likely closed.\r")
                            break
                        logger.debug(
                            f"(non-tty): Error reading/writing on parent stdin: {e}\r")
                        break
                    except Exception as e:
                        logger.debug(
                            f"(non-tty): Unexpected error during stdin read: {e}\r")
                        break

        async def read_pty_and_write_to_parent_stdout(fd_master: int) -> None:
            """Reads output from the PTY master and writes it to parent's stdout."""
            while True:
                try:
                    # Use to_thread to run blocking os.read in a separate thread
                    output_bytes: bytes = await asyncio.to_thread(os.read, fd_master,
                                                                  4096)
                    if not output_bytes:  # PTY closed or EOF
                        logger.debug("PTY Master closed or EOF.\r")
                        break
                    # Write directly to parent's stdout buffer and flush
                    sys.stdout.buffer.write(output_bytes)
                    sys.stdout.buffer.flush()
                except OSError as e:
                    if e.errno == errno.EIO:
                        logger.debug("EIO error, PTY master likely closed.\r")
                        break
                    logger.debug(
                        f"Error reading/writing from PTY master: {e}\r")
                    break
                except Exception as e:
                    logger.debug(f"Unexpected error during PTY read: {e}\r")
                    break

        # Start the asynchronous tasks
        read_input_task: asyncio.Task[None] = asyncio.create_task(
            read_parent_input_and_write_to_pty(master_fd)
        )
        write_output_task: asyncio.Task[None] = asyncio.create_task(
            read_pty_and_write_to_parent_stdout(master_fd)
        )

        print(
            "Bash launched, you can interact with it in conditions similar to "
            "the sandbox. \r"
            "Type 'exit' to quit bash.\r\n\r",flush=True)
        # Wait for the bash subprocess to terminate
        return_code: int = await process.wait()
        logger.debug(f"bash terminated with exit code: {return_code}\r")

        # Cancel the input/output reading tasks after the child process ends
        read_input_task.cancel()
        write_output_task.cancel()
        # Await their completion (to handle CancellationError gracefully)
        try:
            await read_input_task
        except asyncio.CancelledError:
            pass
        try:
            await write_output_task
        except asyncio.CancelledError:
            pass
        sys.exit(return_code)

    finally:
        # Restore parent terminal settings if they were modified
        if is_stdin_a_tty and old_settings:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
                logger.debug("Terminal settings restored.")
            except termios.error as e:
                logger.debug(
                    f"Warning - Could not restore terminal settings: {e}")
            except Exception as e:
                logger.debug(f"Unexpected error during terminal restore: {e}")

        # Close the master file descriptor if it's still open
        if 'master_fd' in locals() and master_fd is not None:
            try:
                os.close(master_fd)
                logger.debug("master_fd closed.")
            except OSError as e:
                if e.errno != errno.EBADF:  # Ignore "Bad file descriptor" if already closed
                    logger.debug(f"Error closing master_fd: {e}")


async def main():
    from pysandboxes.remote.os_sandbox import providers

    parser = argparse.ArgumentParser(
        description="A script demonstrating command-line argument parsing for log verbosity.",
        formatter_class=argparse.HelpFormatter
        # Use default HelpFormatter for clear output
    )

    # Add the verbose argument.
    # action='count' is key here: it counts how many times the argument is present.
    parser.add_argument(
        '-v', '--verbose',
        action='count',
        default=0,  # Default value if no -v is provided
        help='Increase output verbosity. Use -v for INFO, -vv for DEBUG, -vvv for all messages.'
    )

    # Add the --sandbox-provider argument
    parser.add_argument(
        '--os-sandbox', "-p",
        type=str,
        default=None,
        help='Specify the os-sandbox provider (e.g., "subprocess","firejail", "bwrap", "TODO").',
        metavar="<PROVIDER>",
    )
    args = parser.parse_args()

    configure_logging_level(args.verbose)

    provider = providers.get(args.os_sandbox or DEFAULT_OS_SANDBOX)
    assert isinstance(provider,
                      BaseSubProcessDaemon), "The os-sandbox provider must be a BaseSubProcessDaemon"
    envs=dotenv.dotenv_values()
    envs={"PWD":"/home/pprados/workspace.bda/langgraph-codeagent"}  # FIXME
    sandbox_args, kwargs = provider.bash_args(envs)
    if args.verbose >0:
        print("#!/bin/bash\n"+
            sandbox_args[0]+" "+
              " \\\n  ".join(param if " " not in param else repr(param)for param in sandbox_args[1:])+
              "\n",
              file=sys.stderr)
    await run_bash_in_pty(*sandbox_args, **kwargs)


if __name__ == "__main__":
    # Ensure the script is run on a compatible OS
    if sys.platform not in ["linux", "darwin"]:
        print("This script is designed for Linux/macOS as it uses the 'pty' module.")
        print("On Windows, a different approach (e.g., winpty) would be necessary.")
        sys.exit(1)

    asyncio.run(main())
