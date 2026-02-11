import asyncio
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path

from pysandboxes.config import CONFIG_NAME
from pysandboxes.e import ConfigSyntaxError
from pysandboxes.os_sandbox import providers_factory
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.python_in_sb import convert_extra_rules
from pysandboxes.remote.subprocess_daemon import BaseSubProcessDaemon, \
    DaemonParameters, get_log_formatter, launch_sandbox
from pysandboxes.sb_types import Envs
from .remote.parse_cpython_args import parse_python_cmd_line

logger = logging.getLogger(__name__)


def main() -> int:  # FIXME: vérifier sauvegarde en cas de learning
    """
    Parses command-line arguments and run the cpython in sandbox
    """
    python_parsed_args, sandboxes_args, python_cmd = parse_python_cmd_line(sys.argv[1:])

    extra_rules = convert_extra_rules(sandboxes_args)
    if "learning" in extra_rules:
        v = extra_rules["learning"]
        if not v or '' in v:
            extra_rules["learning"] = CONFIG_NAME

    try:
        all_rules = load_and_parse_config(
            config_path=Path(extra_rules.get("learning", CONFIG_NAME)),
            envs=dict(os.environ),  # Use current environ
            **extra_rules
        )
    except ConfigSyntaxError as e:
        print(str(e), file=sys.stderr)
        sys.exit(-1)

    token = str(uuid.uuid4())
    log_level = logging.getLogger().getEffectiveLevel()

    os_provider: BaseSubProcessDaemon = providers_factory[all_rules.os_sandbox](
        token,
        python_args=python_parsed_args
    )
    if not isinstance(os_provider, BaseSubProcessDaemon):
        async def run_locally():
            try:
                await os_provider.start(
                    all_rules,
                    log_level=log_level,
                    envs=None,
                    init_fn=None
                )
                from .remote.python_in_sb import python_in_sb
                python_in_sb(all_rules, python_cmd)
            finally:
                await os_provider.shutdown()
            return 0

        return asyncio.run(run_locally())
    cmd = os_provider.subprocess_cmd(
        all_rules,
        envs=dict(all_rules.envs)  # Use the transformed version
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
        pipe_path.unlink(missing_ok=True)
        python_cmd.extend(
            ["--_named-pipe", str(pipe_path),
             "--_python-sb"
             ])
        token = str(uuid.uuid4())

        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            token=token,
            init_fn=""
        )
        if all_rules.learning:
            env = {**os.environ, **all_rules.envs}
        else:
            env = all_rules.envs

        async def launch_and_wait():
            process = await launch_sandbox(
                cmd + python_cmd,
                pipe_path,
                envs=Envs(env),
                process_config=process_config,
            )
            return await process.wait()

        return_code = asyncio.run(
            launch_and_wait()
        )
        return return_code


if __name__ == "__main__":
    rc = 0
    try:
        rc = main()
    except SystemExit as e:
        rc = int(e.code)
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        rc = -1
    os._exit(rc)
