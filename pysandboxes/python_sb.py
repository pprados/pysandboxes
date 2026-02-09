import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

from pysandboxes.config import CONFIG_NAME
from pysandboxes.os_sandbox import providers_factory
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.python_in_sb import _convert_extra_rules
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

    extra_rules = _convert_extra_rules(sandboxes_args)
    if "learning" in extra_rules:
        v = extra_rules["learning"]
        if not v or '' in v:
            extra_rules["learning"] = CONFIG_NAME

    all_rules = load_and_parse_config(
        exit_on_error=True,
        **extra_rules
    )
    token = str(uuid.uuid4())

    os_provider: BaseSubProcessDaemon = providers_factory[all_rules.os_sandbox](
        token,
        python_args=python_parsed_args
    )
    cmd = os_provider.subprocess_cmd(
        all_rules,
        envs=Envs(os.environ)  # FIXME: valider
    )
    pipe_path = Path("/tmp/toto")  # FIXME
    pipe_path.unlink(missing_ok=True)
    python_cmd.extend(
        ["--_named-pipe", str(pipe_path),
         "--_python-sb"
         ])
    token = str(uuid.uuid4())

    log_level = logging.getLogger().getEffectiveLevel()
    process_config = DaemonParameters(
        all_rules=all_rules,
        log_level=log_level,
        log_format=get_log_formatter(),
        token=token,
        init_fn=""
    )
    asyncio.run(
        launch_sandbox(
            cmd + python_cmd,
            pipe_path,
            dict(os.environ),
            process_config,
            wait=True,
        )
    )
    return 0  # Errorlevel


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
    sys.exit(rc)
