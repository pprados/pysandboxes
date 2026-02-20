import asyncio
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, cast

from pysandboxes.config import CONFIG_NAME
from pysandboxes.e import ConfigSyntaxError
from pysandboxes.os_sandbox import providers_factory
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.python_in_sb import convert_extra_rules
from pysandboxes.remote.sse_client_subprocess_daemon import (
    BaseSubProcessDaemon,
    DaemonParameters,
    get_log_formatter,
    launch_sandbox,
)
from pysandboxes.sb_types import Envs
from pysandboxes.tools import Environ

from .remote.parse_cpython_args import parse_python_cmd_line

logger = logging.getLogger(__name__)


def _debug_log() -> None:
    level = logging.WARNING  # FIX_RELEASE
    format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=format)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp_sse_client.client").setLevel(logging.WARNING)
    logging.getLogger("Pysandboxes").setLevel(level)
    logging.getLogger("pysandboxes").setLevel(level)
    logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(level)


def main() -> int:
    """
    Parses command-line arguments and run the cpython in sandbox
    """
    _debug_log()
    python_parsed_args, sandboxes_args, python_cmd = parse_python_cmd_line(sys.argv[1:])

    extra_rules = convert_extra_rules(sandboxes_args)

    # Add extra to manage ipython
    try:
        import IPython  # noqa: F401

        binds = extra_rules.get("bind", set())  # bind=~/.ipython,~/.ipython
        binds.add("~/.ipython,~/.ipython")
        extra_rules["bind"] = binds
    except ImportError:
        pass  # Ignore. IPython not found

    config_path = Path()
    if len(extra_rules.get("learn", [])):
        config_path = Path(list(extra_rules["learn"])[0])
    if config_path == Path():
        config_path = Path(CONFIG_NAME)

    try:
        from importlib.resources import files

        if (
            "/" not in str(config_path)
            and len(python_cmd) >= 2
            and python_cmd[0] == "-m"
        ):
            # learn is a filename, not a full filename
            # and use -m syntax. So search the config file in the module
            caller_module = python_cmd[1].split(".", 1)[0]
            resource_path = files(caller_module)
            resource_config = str(resource_path) / config_path
            if resource_config and resource_config.exists():
                config_path = resource_config

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
    if not isinstance(os_provider, BaseSubProcessDaemon):

        async def run_locally():
            try:
                await os_provider._start(
                    all_rules, log_level=log_level, envs=None, init_fn=None
                )
                from .remote.python_in_sb import python_in_sb

                python_in_sb(all_rules, python_cmd)
            finally:
                await os_provider._shutdown(graceful_shutdown=True)
            return 0

        return asyncio.run(run_locally())
    with tempfile.TemporaryDirectory() as tmpdir:
        pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
        pipe_path.unlink(missing_ok=True)
        cmd = os_provider.subprocess_cmd(
            all_rules,
            envs=os.environ,
            pipe_path=pipe_path,
        )
        python_cmd.extend(["--_named-pipe", str(pipe_path), "--_python-sb"])
        token = str(uuid.uuid4())

        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            token=token,
            port=0,
            init_fn="",
        )
        env: Environ
        if all_rules.learn:
            env = {**os.environ, **all_rules.envs}
        else:
            env = all_rules.envs

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
