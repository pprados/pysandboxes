# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import asyncio
import logging
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, cast

from ._os_sandbox import providers_factory
from .config import DEBUG
from .e import ConfigSyntaxError
from .main_logger import config_log
from .py_sandbox import load_and_parse_config
from .remote.client_subprocess_sse_daemon import (
    BaseSubProcessDaemon,
    DaemonParameters,
    find_free_port,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .remote.none_daemon import NoneDaemon
from .remote.parse_cpython_args import parse_python_cmd_line
from .remote.python_in_sb import convert_extra_rules
from .sb_types import Envs
from .tools import Environ

# Default console size when not a TTY (e.g. CI, pipes)
_DEFAULT_COLUMNS = 80
_DEFAULT_LINES = 24


def _get_terminal_size() -> tuple[int, int]:
    """Return (columns, lines) from the current terminal, or defaults when not a TTY."""
    try:
        size = os.get_terminal_size()
        return (size.columns, size.lines)
    except OSError:
        pass
    try:
        cols = int(os.environ.get("COLUMNS", str(_DEFAULT_COLUMNS)))
        lines = int(os.environ.get("LINES", str(_DEFAULT_LINES)))
        return (max(1, cols), max(1, lines))
    except (ValueError, TypeError):
        return (_DEFAULT_COLUMNS, _DEFAULT_LINES)


logger = logging.getLogger(__name__)

# QEMU console sentinels: guest prints these to stderr; host forwards only lines between them
PYTHON_OUTPUT_START = "[PYSANDBOXES]PYTHON_OUTPUT_START"
PYTHON_OUTPUT_END = "[PYSANDBOXES]PYTHON_OUTPUT_END"

# QEMU console filter state: 0=waiting for start sentinel, 1=forwarding, 2=stopped
_FORWARD_STATE_WAITING = 0
_FORWARD_STATE_FORWARDING = 1
_FORWARD_STATE_STOPPED = 2

# Strip kernel/cloud-init style prefix e.g. "[   12.525772] cloud-init[672]: "
_QEMU_CONSOLE_PREFIX = re.compile(r"^\s*\[\s*\d+\.\d+\]\s*[\w-]+\[\d+\]:")


def _qemu_forward_state_for_line(line: str, state: list[int]) -> bool:
    """Update state from line (start/end sentinels) and return True if line should be printed."""
    s = state[0]
    if s == _FORWARD_STATE_WAITING:
        if PYTHON_OUTPUT_START in line:
            state[0] = _FORWARD_STATE_FORWARDING
        return False
    if s == _FORWARD_STATE_FORWARDING:
        if PYTHON_OUTPUT_END in line:
            state[0] = _FORWARD_STATE_STOPPED
            return False
        return True
    return False  # _FORWARD_STATE_STOPPED


async def _qemu_read_and_forward(
    stream: asyncio.StreamReader | None,
    is_stderr: bool,
    state: list[int],
    *,
    forward_all: bool = False,
) -> None:
    """Read QEMU console stream and forward lines (all if forward_all, else between sentinels)."""
    if stream is None:
        return
    out = sys.stderr if is_stderr else sys.stdout
    while True:
        try:
            line = await stream.readline()
        except (ConnectionResetError, BrokenPipeError):
            break
        if not line:
            break
        try:
            text = line.decode("utf-8", errors="replace")
        except Exception:
            text = str(line)
        text_stripped = _QEMU_CONSOLE_PREFIX.sub("", text)
        if forward_all or _qemu_forward_state_for_line(text_stripped, state):
            print(text_stripped, end="", file=out, flush=True)


async def _qemu_wait_and_filter_console(
    process: asyncio.subprocess.Process,
    *,
    forward_all: bool = False,
) -> int:
    """Wait for QEMU process and forward console output (all if forward_all, else between sentinels)."""
    state: list[int] = [_FORWARD_STATE_WAITING]
    t_stdout = asyncio.create_task(
        _qemu_read_and_forward(process.stdout, False, state, forward_all=forward_all)
    )
    t_stderr = asyncio.create_task(
        _qemu_read_and_forward(process.stderr, True, state, forward_all=forward_all)
    )
    exit_code = await process.wait()
    await t_stdout
    await t_stderr
    return exit_code if exit_code is not None else -1


def _debug_log() -> None:
    sandbox_level = logging.DEBUG
    uvicorn_log_level = logging.ERROR
    format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
    config_log(sandbox_level)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(uvicorn_log_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_log_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_log_level)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandbox_level)
    logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(sandbox_level)
    logging.info("Start with python-sb")
    logging.basicConfig(
        level=sandbox_level,
        format=format,
    )


def main() -> int:
    """
    Parses command-line arguments and run the cpython in sandbox
    """
    if DEBUG:
        _debug_log()

    python_parsed_args, sandboxes_args, python_cmd, config_path = parse_python_cmd_line(
        sys.argv[1:]
    )

    extra_rules = convert_extra_rules(sandboxes_args)

    # Add extra to manage ipython
    try:
        import IPython  # noqa: F401

        binds = extra_rules.get("bind", set())
        if Path("~/.ipython").expanduser().is_dir():
            binds.add("~/.ipython,~/.ipython")
            extra_rules["bind"] = binds
    except ImportError:
        pass  # Ignore. IPython not found

    # If --learn and --pysandboxes-config=xxx, use --learn=xxx
    # If --learn and not --pysandboxes-config, use --learn=CONFIG_NAME
    # If -m module  use resource module/.py-sandboxes
    try:
        envs = extra_rules.get("env", set())
        envs.add("TERM=${TERM}")
        extra_rules["env"] = envs
        all_rules = load_and_parse_config(
            config_path=config_path,
            envs=os.environ,  # Use current environ
            **cast(Mapping[str, Any], extra_rules),
        )
    except ConfigSyntaxError as e:
        print(str(e), file=sys.stderr)
        sys.exit(-1)

    token = str(uuid.uuid4())
    log_level = logging.getLogger().getEffectiveLevel()

    os_provider: BaseSubProcessDaemon = providers_factory[all_rules.os_sandbox](
        token, python_args=python_parsed_args
    )
    logger.debug(f"{os_provider=} {all_rules.learn=}")
    if "--version" in python_parsed_args:
        print("Python", ".".join(map(str, sys.version_info[0:3])))
        sys.exit(0)
    if isinstance(os_provider, NoneDaemon):
        from .remote.python_in_sb import python_in_sb

        return python_in_sb(all_rules, python_cmd)
    with tempfile.TemporaryDirectory() as tmpdir:
        pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
        pipe_path.unlink(missing_ok=True)
        if all_rules.os_sandbox == "qemu":
            # For QEMU: build process_config before subprocess_cmd so the ISO
            # can be created with the config embedded.
            from pysandboxes.remote.qemu_setup import GUEST_RUN_MOUNT  # FIXME

            os_provider.port = (
                find_free_port() if all_rules.port == -1 else all_rules.port
            )
            token = str(uuid.uuid4())
            # Propagate host terminal size to guest so console width/height match
            columns, lines = _get_terminal_size()
            guest_envs = Envs(
                {
                    **dict(all_rules.envs),
                    "COLUMNS": str(columns),
                    "LINES": str(lines),
                }
            )
            guest_all_rules = all_rules._replace(envs=guest_envs)
            process_config = DaemonParameters(
                all_rules=guest_all_rules,
                log_level=log_level,
                log_format=get_log_formatter(),
                use_rich_handler=use_rich_handler(),
                token=token,
                port=os_provider.port,
                init_fn="",
                python_main_args=tuple(python_cmd),
                guest_run_dir=GUEST_RUN_MOUNT,
            )
            # Store config so subprocess_cmd can build ISO and 9p config dir; guest reads config from 9p
            os_provider._iso_config = process_config  # type: ignore[attr-defined]
            cmd, extra_envs = os_provider.subprocess_cmd(
                all_rules, envs=os.environ, pipe_path=pipe_path, temp=Path(tmpdir)
            )
            # Config is in 9p-mounted config dir, no FIFO
            config_writer = lambda _: None
        else:
            cmd, extra_envs = os_provider.subprocess_cmd(
                all_rules, envs=os.environ, pipe_path=pipe_path, temp=Path(tmpdir)
            )
            python_cmd.extend(["--_named-pipe", str(pipe_path), "--_python-sb"])
            token = str(uuid.uuid4())
            process_config = DaemonParameters(
                all_rules=all_rules,
                log_level=log_level,
                log_format=get_log_formatter(),
                use_rich_handler=use_rich_handler(),
                token=token,
                port=0,
                init_fn="",
                python_main_args=(),
            )
            config_writer = None

        env: Environ
        if all_rules.learn:
            env = {**os.environ, **all_rules.envs}
        else:
            env = dict(all_rules.envs)
        env = {**env, **extra_envs}

        # Get optional launch extras (preexec_fn, pass_fds) for providers
        # that need custom child setup (e.g., unshare with slirp4netns fd)
        extra_preexec_fn, pass_fds = os_provider.get_launch_extras()

        launch_args = cmd if all_rules.os_sandbox == "qemu" else cmd + python_cmd

        async def launch_and_wait() -> int:
            if all_rules.os_sandbox == "qemu":
                show_boot = all_rules.os_sandbox_params.get(
                    "qemu.show_boot_console", "false"
                ).lower() in ("true", "1", "yes")
                qemu_console_file = None
                launch_kwargs: dict[str, Any] = dict(
                    cmd=launch_args,
                    pipe_path=pipe_path,
                    envs=Envs(env),
                    process_config=process_config,
                    extra_preexec_fn=extra_preexec_fn,
                    pass_fds=pass_fds,
                    on_launched=os_provider.on_process_launched,
                    config_writer=config_writer,
                )
                if not show_boot:
                    launch_kwargs["stdout"] = subprocess.PIPE
                    launch_kwargs["stderr"] = subprocess.PIPE
                else:
                    qemu_console_path = Path(
                        os.environ.get(
                            "PYSANDBOXES_QEMU_CONSOLE_LOG",
                            ".pysandbox-qemu-console.log",
                        )
                    )
                    qemu_console_file = open(qemu_console_path, "w")
                    try:
                        logger.debug(
                            "QEMU guest console → %s",
                            qemu_console_path.resolve(),
                        )
                        logger.debug(
                            "Run in another terminal: tail -f %s (to see guest output including 'Calling sandbox at...')",
                            qemu_console_path.resolve(),
                        )
                        launch_kwargs["stdout"] = qemu_console_file.fileno()
                        launch_kwargs["stderr"] = qemu_console_file.fileno()
                    except Exception:
                        qemu_console_file.close()
                        raise
                process = await launch_sandbox(**launch_kwargs)
                try:
                    if (
                        not show_boot
                        and process.stdout is not None
                        and process.stderr is not None
                    ):
                        return await _qemu_wait_and_filter_console(
                            process, forward_all=DEBUG
                        )
                    return await process.wait()
                finally:
                    if qemu_console_file is not None:
                        qemu_console_file.close()
                    kill_slirp = getattr(os_provider, "_kill_slirp", None)
                    if callable(kill_slirp):
                        kill_slirp()
            else:
                process = await launch_sandbox(
                    launch_args,
                    pipe_path,
                    envs=Envs(env),
                    process_config=process_config,
                    extra_preexec_fn=extra_preexec_fn,
                    pass_fds=pass_fds,
                    on_launched=os_provider.on_process_launched,
                    config_writer=config_writer,
                )
                try:
                    return await process.wait()
                finally:
                    kill_slirp = getattr(os_provider, "_kill_slirp", None)
                    if callable(kill_slirp):
                        kill_slirp()

        logger.debug("Launching sandbox (waiting for guest to finish)...")
        return_code = asyncio.run(launch_and_wait())
        logger.debug("Guest process finished (exit code %s)", return_code)
        # For QEMU, guest writes exit code to shared run dir; use it if present
        if all_rules.os_sandbox == "qemu":
            exitcode_file = Path(tmpdir) / "exitcode"
            if exitcode_file.exists():
                try:
                    raw = exitcode_file.read_text().strip()
                    return_code = int(raw)
                except (ValueError, OSError):
                    pass
        return return_code


if __name__ == "__main__":
    rc = 0
    try:
        rc = main()
    except SystemExit as e:
        if e.code is not None:
            rc = int(e.code)
        else:
            rc = 0
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        rc = -1
    if not sys.stdout.closed:
        sys.stdout.flush()
    if not sys.stderr.closed:
        sys.stderr.flush()
    os._exit(rc)
