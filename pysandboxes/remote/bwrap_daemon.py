import logging
import os
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
        major, minor, release_level,*_ = sys.version_info

        # Same place
        args.extend(["--ro-bind", get_venv(), get_venv()])
        args.extend(["--ro-bind", get_venv(), "/usr/local"])
        # args.extend(["--ro-bind",
        #              f"/usr/lib/python{major}.{minor}/encodings",
        #              f"/usr/lib/python{major}.{minor}/encodings"])

        # Extend mapping if the python version use a link
        prg = sys.executable
        while os.path.islink(prg):
            prg = os.readlink(prg)
            if ".pyenv" in prg:
                prg=prg[:(prg.find(".pyenv/")+len(".pyenv/"))]
            args.extend(["--ro-bind", os.path.dirname(prg), os.path.dirname(prg)])

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

    def _subprocess(self) -> List[str]:
        args=self._bwrap_args()
        args.extend([
            "/bin/bash", "--norc", "--noprofile",
            # "/usr/local/bin/python", "-m", f"--outer-sandbox={provider}", daemon.__name__
        ])
        return args

    def bash_args(self) -> Tuple[List[str], Dict[str, str]]:
        args=self._bwrap_args()
        args.extend([
            "--setenv","PS1","[sandbox-bwrap] $ ",
            "--ro-bind","/bin","/bin",
            "--ro-bind","/lib","/lib",
            "--ro-bind","/lib64","/lib64",
            "/bin/bash", "--norc", "--noprofile", "-i",
        ])
        return args,{}

