import logging
import shlex
import sys
from pathlib import Path
from typing import List, Dict, Tuple

from . import daemon
from .subprocess_daemon import SubProcessDaemon, BaseSubProcessDaemon
from .tools import which_command, get_venv
from ..guard_files import BindRule
from ..guard_sandbox import read_and_parse_config
from ..tools import read_config

logger = logging.getLogger(__name__)


class BWrapDaemon(BaseSubProcessDaemon):
    def _bwrap_args(self) -> List[str]:

        from importlib.resources import files
        # Reads contents with UTF-8 encoding and returns str.
        sandbox_env, provider, socket_rules, files_rules = read_and_parse_config()

        # assert provider == "bwrap"
        bwrap_conf = read_config(Path(files(__name__).joinpath('bwrap.cmd-template')))

        args = [str(which_command("bwrap"))]
        for line in bwrap_conf:
            args.extend(shlex.split(line))

        for env, val in sandbox_env.items():
            args.extend(["--setenv", env, val])

        # Add python venv
        major, minor, *_ = sys.version_info
        args.extend(["--ro-bind", get_venv(), "/usr/local"])
        # Extend mapping if the python version use a link
        prg = Path(sys.executable)
        while prg.is_symlink():
            prg = prg.readlink()
            args.extend(["--ro-bind", str(prg.parent), str(prg.parent)])

        for rule in files_rules:
            if isinstance(rule, BindRule):
                if rule.write:
                    args.extend(["--bind", rule.source, rule.dest])
                else:
                    args.extend(["--ro-bind", rule.source, rule.dest])

        # TODO
        for rule in socket_rules:
            pass

        # TODO: manage /tmp
        # --tmpfs DEST
        return args

    def shell_args(self) -> Tuple[List[str], Dict[str, str]]:
        args=self._bwrap_args()
        args.extend([
            "/bin/bash", "--norc", "--noprofile",
        ])
        return args,{}

    def _subprocess(self) -> List[str]:
        args=self._bwrap_args()
        args.extend([
            "/bin/bash", "--norc", "--noprofile",
            # "/usr/local/bin/python", "-m", f"--outer-sandbox={provider}", daemon.__name__
        ])
        print("----------")
        print('"' + "\" \\\n\"".join(args) + '"')
        return args