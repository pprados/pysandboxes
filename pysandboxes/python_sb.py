# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import asyncio
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, cast

from pysandboxes._os_sandbox import providers_factory
from pysandboxes.config import DEBUG
from pysandboxes.e import ConfigSyntaxError
from pysandboxes.main_logger import config_log
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.none_daemon import NoneDaemon
from pysandboxes.remote.python_in_sb import convert_extra_rules
from pysandboxes.remote.sse_client_subprocess_daemon import (
    BaseSubProcessDaemon,
    DaemonParameters,
    find_free_port,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from pysandboxes.sb_types import Envs
from pysandboxes.tools import Environ

from .remote.parse_cpython_args import parse_python_cmd_line

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
    with tempfile.TemporaryDirectory() as tmpdir:
        pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
        pipe_path.unlink(missing_ok=True)
        if all_rules.os_sandbox == "qemu":
            # For QEMU: build process_config before subprocess_cmd so the ISO
            # can be created with the config embedded (no HTTP server needed).
            os_provider.port = (
                find_free_port() if all_rules.port == -1 else all_rules.port
            )
            token = str(uuid.uuid4())
            process_config = DaemonParameters(
                all_rules=all_rules,
                log_level=log_level,
                log_format=get_log_formatter(),
                use_rich_handler=use_rich_handler(),
                token=token,
                port=os_provider.port,
                init_fn="",
                python_main_args=tuple(python_cmd),
            )
            # Store config so subprocess_cmd can embed it in the ISO
            os_provider._iso_config = process_config  # type: ignore[attr-defined]
            cmd, extra_envs = os_provider.subprocess_cmd(
                all_rules, envs=os.environ, pipe_path=pipe_path, temp=Path(tmpdir)
            )
            config_writer = lambda _: None  # config already embedded in ISO
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

        return_code = asyncio.run(launch_and_wait())
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
