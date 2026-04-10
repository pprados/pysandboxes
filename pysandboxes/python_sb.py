# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, TextIO, cast

from ._os_sandbox import providers_factory
from .config import DEBUG
from .e import ConfigSyntaxError
from .main_logger import config_log
from .py_sandbox import load_and_parse_config
from .remote import qemu_guest_console_io as _qemu_guest_console_io
from .remote.client_subprocess_sse_daemon import (
    BaseSubProcessDaemon,
    find_free_port,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .remote.daemon_parameters import DaemonParameters
from .remote.none_daemon import NoneDaemon
from .remote.parse_cpython_args import parse_python_cmd_line
from .remote.python_in_sb import convert_extra_rules
from .remote.qemu_setup import QEMU_HOST_RUN_PREFIX
from .sb_types import Envs
from .tools import Environ

# Re-export for ``main_sandbox`` / external use
PYTHON_OUTPUT_END = _qemu_guest_console_io.PYTHON_OUTPUT_END
PYTHON_OUTPUT_START = _qemu_guest_console_io.PYTHON_OUTPUT_START
qemu_wait_and_filter_console = _qemu_guest_console_io.qemu_wait_and_filter_console
read_qemu_guest_exitcode = _qemu_guest_console_io.read_qemu_guest_exitcode

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
    _host_tmp = "/tmp" if os.path.isdir("/tmp") else None
    _run_prefix = (
        QEMU_HOST_RUN_PREFIX if all_rules.os_sandbox == "qemu" else "pysandboxes-sb-"
    )
    with tempfile.TemporaryDirectory(prefix=_run_prefix, dir=_host_tmp) as tmpdir:
        pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
        pipe_path.unlink(missing_ok=True)
        if all_rules.os_sandbox == "qemu":
            # For QEMU: build process_config before subprocess_cmd so the ISO
            # can be created with the config embedded.
            from .remote.qemu_setup import (
                GUEST_RUN_MOUNT,
                _qemu_show_boot_console_truthy,
                augment_all_rules_for_qemu_run_mount,
            )

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
            guest_all_rules = augment_all_rules_for_qemu_run_mount(
                all_rules._replace(envs=guest_envs)
            )
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
                guest_working_dir=str(Path.cwd().resolve()),
            )
            # Store config so subprocess_cmd can build ISO and 9p config dir; guest reads config from 9p
            os_provider._iso_config = process_config  # type: ignore[attr-defined]
            cmd, extra_envs = os_provider.subprocess_cmd(
                all_rules, envs=os.environ, pipe_path=pipe_path, temp=Path(tmpdir)
            )
            # Config is in 9p-mounted config dir, no FIFO
            config_writer = lambda _: None
        else:
            os_provider.port = (
                find_free_port() if all_rules.port == -1 else all_rules.port
            )
            cmd, extra_envs = os_provider.subprocess_cmd(
                all_rules, envs=os.environ, pipe_path=pipe_path, temp=Path(tmpdir)
            )
            python_cmd.extend(["--_named-pipe", str(pipe_path), "--_python-sb"])
            token = str(uuid.uuid4())
            default_process_config = DaemonParameters(
                all_rules=all_rules,
                log_level=log_level,
                log_format=get_log_formatter(),
                use_rich_handler=use_rich_handler(),
                token=token,
                port=os_provider.port,
                init_fn="",
                python_main_args=(),
            )
            launch_params = getattr(
                os_provider,
                "get_launch_params_for_python_sb",
                lambda *a, **k: {},
            )(all_rules, log_level, token, "", pipe_path, Path(tmpdir))
            process_config = launch_params.get("process_config", default_process_config)
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
                show_boot = _qemu_show_boot_console_truthy(all_rules)
                qemu_console_file: TextIO | None = None
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
                # Always use pipes so we can filter (sentinels) or tee to terminal + log file.
                launch_kwargs["stdout"] = subprocess.PIPE
                launch_kwargs["stderr"] = subprocess.PIPE
                if show_boot:
                    qemu_console_path = Path(".pysandbox-qemu-console.log")
                    qemu_console_file = open(qemu_console_path, "w")
                    logger.debug(
                        "QEMU guest console (terminal + tee) → %s",
                        qemu_console_path.resolve(),
                    )
                try:
                    process = await launch_sandbox(**launch_kwargs)
                    try:
                        if process.stdout is None or process.stderr is None:
                            return await process.wait()
                        # Full VM console only when qemu.show_boot_console=true (profile).
                        forward_all = show_boot
                        return await qemu_wait_and_filter_console(
                            process,
                            forward_all=forward_all,
                            tee_file=qemu_console_file,
                        )
                    finally:
                        kill_slirp = getattr(os_provider, "_kill_slirp", None)
                        if callable(kill_slirp):
                            kill_slirp()
                finally:
                    if qemu_console_file is not None:
                        qemu_console_file.close()
            else:
                process = await launch_sandbox(
                    launch_args,
                    pipe_path,
                    envs=Envs(env),
                    process_config=process_config,
                    extra_preexec_fn=extra_preexec_fn,
                    pass_fds=launch_params.get("pass_fds", pass_fds),
                    on_launched=launch_params.get(
                        "on_launched", os_provider.on_process_launched
                    ),
                    config_writer=config_writer,
                )
                try:
                    return await process.wait()
                finally:
                    kill_slirp = getattr(os_provider, "_kill_slirp", None)
                    if callable(kill_slirp):
                        kill_slirp()

        logger.debug("Launching sandbox (waiting for guest to finish)...")
        qemu_wait_rc = asyncio.run(launch_and_wait())
        return_code = qemu_wait_rc
        logger.debug("Guest process finished (QEMU wait exit code %s)", return_code)
        # For QEMU, guest writes exit code to shared run dir; prefer it over QEMU's
        # process status (9p latency; QEMU may return non-zero on shutdown I/O).
        if all_rules.os_sandbox == "qemu":
            exitcode_file = Path(tmpdir) / "exitcode"
            guest_rc = read_qemu_guest_exitcode(exitcode_file)
            logger.debug(
                "QEMU exitcode: guest_rc=%s qemu_wait=%s file=%s",
                guest_rc,
                qemu_wait_rc,
                exitcode_file,
            )
            if guest_rc is not None:
                return_code = guest_rc
            elif qemu_wait_rc == 0:
                logger.debug(
                    "No guest exitcode at %s after wait; treating as failure",
                    exitcode_file,
                )
                return_code = 1
            else:
                return_code = qemu_wait_rc
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
