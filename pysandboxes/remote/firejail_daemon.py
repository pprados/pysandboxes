import logging
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple, Dict

import click

from pysandboxes.guard_files import BindRule, IgnoreRule
from pysandboxes.guard_sandbox import read_and_parse_config, AllRules
from pysandboxes.netfilter import rule_to_netfilter
from pysandboxes.remote import daemon, subprocess_daemon
from pysandboxes.remote.subprocess_daemon import BaseSubProcessDaemon
from pysandboxes.remote.tools import which_command, get_venv, get_default_gateway_info, \
    suggest_package_installation, return_level_parameter
from pysandboxes.tools import read_config, substitute_env_vars

logger = logging.getLogger(__name__)

DEBUG = subprocess_daemon.DEBUG


class FireJailDaemon(BaseSubProcessDaemon):
    def update_rules(self,envs: Dict[str, str]):
        _,all_rules=self._firejail_args(envs)
        return all_rules

    def _firejail_args(self, envs: Dict[str, str]) -> Tuple[List[str],AllRules]:

        if not which_command("firejail"):
            logger.error("firejail not found. Install it with:")
            logger.error(suggest_package_installation("firejail"))
            sys.exit(1)

        need_root = False
        from importlib.resources import files
        # Reads contents with UTF-8 encoding and returns str.
        sandbox_env, provider, socket_rules, files_rules = read_and_parse_config(
            envs=envs)

        # assert provider == "firejail"
        args = [str(which_command("firejail"))]

        # Add default parameters
        firejail_conf = read_config(
            Path(files(__name__).joinpath('firejail.profile')))
        firejail_conf = substitute_env_vars(firejail_conf, envs)

        for line in firejail_conf:
            args.extend(shlex.split(line))

        # Extend mapping if the python version use a link
        major, minor, release_level, *_ = sys.version_info
        prg = sys.executable
        while os.path.islink(prg):
            prg = os.readlink(prg)
            # if ".pyenv" in prg:
            #     prg = prg[:(prg.find(".pyenv/") + len(".pyenv/"))]
            args.extend([
                f"--whitelist={os.path.dirname(prg)}",
                f"--read-only={os.path.dirname(prg)}",
            ])

        # Same place
        args.extend([
            f"--whitelist={get_venv()}",
            f"--read-only={get_venv()}",
        ])

        # Add files rules
        new_files_rules=[]
        for rule in files_rules:
            if isinstance(rule, BindRule):
                if rule.source == rule.dest:
                    args.append(f"--whitelist={rule.source}")
                else:
                    # Note: de py-sandbox manager the alias
                    args.append(f"--whitelist={rule.source}")
                    need_root = True
                if not rule.write:
                    args.append(f"--read-only={rule.source}")
            elif isinstance(rule, IgnoreRule):
                args.append(f"--blacklist={rule.source}")
                new_files_rules.append(rule)
        files_rules=new_files_rules

        if socket_rules:
            gw = get_default_gateway_info()
            if gw:  # Initialize the gateway
                # FIXME: pour le dns, j'ai besoin de la gateway localhost
                # C'est bon si le dns est externe et non localhost
                # args.append(f"--defaultgw={gw[0]}")
                # Avec --net, il n'est plus possible de se connecter8 depuis le host
                # args.append(f"--net={gw[1]}")
                pass

            net_filter4 = rule_to_netfilter(socket_rules, is_ipv6=False)
            netfilter_file = tempfile.NamedTemporaryFile(mode='w+t',
                                                         delete=False,  # TODO: manager tmp file?
                                                         encoding='utf-8').name
            if DEBUG:
                netfilter_file = "netfilter.net"
            Path(netfilter_file).write_text("\n".join(net_filter4))
            args.append(f"--netfilter={netfilter_file}")

            net_filter6 = rule_to_netfilter(socket_rules, is_ipv6=True)
            netfilter6_file = tempfile.NamedTemporaryFile(mode='w+t',
                                                          delete=False,  # TODO: manager tmp file?
                                                          encoding='utf-8').name
            if DEBUG:
                netfilter6_file = "netfilter6.net"
            Path(netfilter6_file).write_text("\n".join(net_filter6))
            args.append(f"--netfilter6={netfilter6_file}")

            # Remove redondant sockets rules
            socket_rules=[]  # FIXME: doublon ou non ?

        # TODO: Add tmp rules
        # --tmpfs DEST

        args.extend(["env", "-i"])
        for env, val in sandbox_env.items():
            args.append(f"{env}={val}")

        if need_root:
            logger.warning("Firejail needs root to run")

        return args,(sandbox_env, provider, socket_rules, files_rules)

    def _subprocess(self,envs:Dict[str,str], log_level:int) -> List[str]:
        cmd_parameters, _ = self._firejail_args(envs=envs)

        cmd_parameters.extend([
            sys.executable,
            "-P",  # don't prepend a potentially unsafe path to sys.path; also PYTHONSAFEPATH

            "-u",  # FIXME unbuffered stdout and stderr
            "-m",
            daemon.__name__,
        ])
        verbose = return_level_parameter(log_level)
        if verbose:
            cmd_parameters.append(verbose)
        cmd_parameters.extend([
            "--outer-sandbox", "firejail",
        ])
        if DEBUG:
            Path("run.sh").write_text(" \\\n".join(cmd_parameters))
        return cmd_parameters

    def bash_args(self, envs: Dict[str, str]) -> Tuple[List[str], Dict[str, str]]:
        args,_ = self._firejail_args(envs)
        args.extend([
            f"PS1={click.style('os-sandbox', fg='cyan')}]-firejail] $ ",  # TODO: color ?
            # "PS1=[os-sandbox]\nfirejail $ ",
            "/bin/bash", "--norc", "--noprofile", "-i",
            # "wget", "-T", "1", "http://octo.com",  # FIXME
        ])
        return args, {}
