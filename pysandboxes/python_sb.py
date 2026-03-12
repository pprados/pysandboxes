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

from pysandboxes.e import ConfigSyntaxError
from pysandboxes.main_logger import config_log
from pysandboxes.os_sandbox import providers_factory
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.none_daemon import NoneDaemon
from pysandboxes.remote.python_in_sb import convert_extra_rules
from pysandboxes.remote.sse_client_subprocess_daemon import (
    BaseSubProcessDaemon,
    DaemonParameters,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from pysandboxes.sb_types import Envs
from pysandboxes.tools import Environ

from .remote.parse_cpython_args import parse_python_cmd_line

logger = logging.getLogger(__name__)


def _debug_log() -> None:
    sandbox_level = logging.DEBUG  # FIX_RELEASE
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
    _debug_log()  # FIX_RELEASE

    python_parsed_args, sandboxes_args, python_cmd, config_path = parse_python_cmd_line(
        sys.argv[1:]
    )

    extra_rules = convert_extra_rules(sandboxes_args)

    # Add extra to manage ipython
    try:
        import IPython  # noqa: F401

        binds = extra_rules.get("bind", set())  # bind=~/.ipython,~/.ipython
        binds.add("~/.ipython,~/.ipython")
        extra_rules["bind"] = binds
    except ImportError:
        pass  # Ignore. IPython not found

    # If --learn and --pysandboxes-config=xxx, use --learn=xxx
    # If --learn and not --pysandboxes-config, use --learn=CONFIG_NAME
    # If -m module  use resource module/.py-sandboxes
    # learn_path: Path
    # if len(extra_rules.get("learn", set())):
    #     learn_path = Path(list(extra_rules["learn"])[0])
    #     if learn_path == Path():
    #         if config_path == Path():
    #             learn_path = Path(CONFIG_NAME)
    #         else:
    #             learn_path = config_path
    #     extra_rules["learn"] = {str(learn_path)}
    # if config_path == Path():
    #     config_path = Path(CONFIG_NAME)
    # if not config_path.exists() and "learn" not in extra_rules:
    #     extra_rules["learn"] = set()
    try:
        envs = extra_rules.get("env", set())
        envs.add("TERM=${TERM}")
        extra_rules["env"] = envs
        # if config_path.is_relative_to(Path()):
        #     logger.info(f"Use {config_path.relative_to(Path())}")
        # else:
        #     logger.info(f"Use {config_path=}")
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
    if isinstance(os_provider, NoneDaemon):
        from .remote.python_in_sb import python_in_sb

        return python_in_sb(all_rules, python_cmd)
    with tempfile.TemporaryDirectory() as tmpdir:
        pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
        pipe_path.unlink(missing_ok=True)
        cmd = os_provider.subprocess_cmd(
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
        )
        env: Environ
        if all_rules.learn:
            env = {**os.environ, **all_rules.envs}
        else:
            env = dict(all_rules.envs)

        async def launch_and_wait() -> int:
            process = await launch_sandbox(
                cmd + python_cmd,
                pipe_path,
                envs=Envs(env),
                process_config=process_config,
            )
            return await process.wait()

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
    os._exit(rc)
