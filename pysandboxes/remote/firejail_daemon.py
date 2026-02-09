import logging
import os
import shlex
import site
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple, MutableSet, Any, Union

import click

from .subprocess_daemon import BaseSubProcessDaemon
from .tools import which_command, suggest_package_installation
from ..guard_files import BindRule, IgnoreRule
from ..main_logger import pysandboxes_logger
from ..netfilter import rule_to_netfilter
from ..all_rules import AllRules
from ..tools import remove_comments, substitute_env_vars
from ..sb_types import Envs, Args

logger = logging.getLogger(__name__)

DEBUG = False


class WhiteList(MutableSet):
    """
    A class that simulates a set of directory paths, implementing a white list logic.

    This class extends MutableSet to provide set-like functionality. It ensures
    that the stored directory paths are unique and adhere to specific prefix rules.
    If a new directory path is a prefix of an existing path, the existing path is
    removed and replaced by the new, more general path. If a new path is already
    prefixed by an existing path, it is not added.
    """

    def __init__(self, directories: list[str] = []) -> None:
        """
        Initializes the WhiteList with an optional list of directory paths.

        Args:
            directories (list[str]): A list of initial directory paths to add.
        """
        self._set: set[str] = set()
        # Add initial directories, applying the whitelist logic.
        for directory in directories:
            self.add(directory)

    def __contains__(self, item: Any) -> bool:
        """
        Checks if a directory path or any of its parent directories is in the WhiteList.

        Args:
            item (Any): The directory path to check.

        Returns:
            bool: True if the item is a string and is in the internal set or is a
                  sub-directory of an existing path, False otherwise.
        """
        # Ensure the item is a string before proceeding.
        if not isinstance(item, str):
            return False

        # Ensure the path ends with a separator for consistent prefix checking.
        if not item.endswith('/'):
            item += '/'

        # Check if the item itself is in the set, or if an existing directory is
        # a prefix of the item. This means the item is a subdirectory of a
        # whitelisted path.
        for existing_dir in self._set:
            if item.startswith(existing_dir):
                return True

        return False

    def __iter__(self):
        """
        Returns an iterator over the directory paths in the WhiteList.
        """
        return iter(self._set)

    def __len__(self) -> int:
        """
        Returns the number of directory paths in the WhiteList.

        Returns:
            int: The number of paths.
        """
        return len(self._set)

    def add(self, directory: str) -> None:
        """
        Adds a new directory path to the WhiteList, applying the prefix rules.

        - If the new directory path is already prefixed by an existing path, it
          is not added.
        - If the new directory path is a prefix of one or more existing paths,
          those paths are removed and the new path is added.

        Args:
            directory (str): The directory path to add.
        """
        # Ensure the path ends with a separator to simplify prefix checks.
        if not directory.endswith('/'):
            directory += '/'

        # Check if an existing directory already prefixes the new one.
        for existing_dir in self._set:
            if directory.startswith(existing_dir):
                return

        # Find existing directories that are prefixed by the new directory.
        to_remove = {
            existing_dir
            for existing_dir in self._set
            if existing_dir.startswith(directory)
        }

        # If any directories are to be removed, perform the replacement.
        if to_remove:
            self._set -= to_remove
            self._set.add(directory)
        else:
            # If no replacements are needed, just add the new directory.
            self._set.add(directory)

    def discard(self, directory: str) -> None:
        """
        Removes a directory path from the WhiteList if it exists.

        Args:
            directory (str): The directory path to remove.
        """
        # Ensure the path ends with a separator for consistency.
        if not directory.endswith('/'):
            directory += '/'
        self._set.discard(directory)


def _follow_links(filename: Union[str, Path], whitelist: WhiteList) -> None:
    whitelist.add(str(filename))
    try:
        if Path(filename).is_symlink():
            whitelist.add(str(Path(filename).resolve(strict=True)))
    except FileNotFoundError:
        raise RuntimeError("Impossible to resolve the sys.executable `%s`",
                           sys.executable)


def _follow_links_executable(executable: Path, whitelist: WhiteList) -> None:
    if executable.parents[0].name == "bin":
        if str(executable.parent.parent) not in whitelist:
            whitelist.add(str(executable.parent.parent))
        else:
            return
    else:
        if str(executable) not in whitelist:
            whitelist.add(str(executable))
        else:
            return
    if executable.is_symlink():
        try:
            _follow_links_executable(executable.resolve(strict=True), whitelist)
        except FileNotFoundError:
            raise RuntimeError("Impossible to resolve the sys.executable `%s`",
                               sys.executable)


class FireJailDaemon(BaseSubProcessDaemon):
    def update_rules(self,
                     *,
                     envs: Envs,
                     all_rules: AllRules) -> AllRules:
        _, all_rules = self._firejail_args(envs,
                                           all_rules)
        return all_rules

    def _firejail_args(self,
                       envs: Envs,
                       all_rules: AllRules,
                       ) -> Tuple[Args, AllRules]:
        """
        Apply the pysandboxes rules to firejail.
        TODO: expliquer si on modifie
        """
        if not which_command("firejail"):
            logger.error("firejail not found. Install it with:")
            logger.error(suggest_package_installation("firejail"))
            logger.error("And set 'restricted-network no'  in "
                         "/etc/firejail/firejail.config")
            sys.exit(1)

        need_root = False
        from importlib.resources import files


        args = [str(which_command("firejail"))]

        if pysandboxes_logger.getEffectiveLevel() > logging.INFO:
            args.append("--quiet")

        # Add default parameters
        firejail_conf = remove_comments(
            Path(files(__name__).joinpath('firejail.profile')).read_text().splitlines())
        firejail_conf = substitute_env_vars(firejail_conf, envs)

        for line in firejail_conf:
            args.extend(shlex.split(line))

        # Extend mapping if the python version use some links
        major, minor, release_level, *_ = sys.version_info
        whitelist = WhiteList()

        # Manage sys.executable
        _follow_links_executable(Path(sys.executable), whitelist)

        for p in sys.path:
            if os.path.isdir(p):
                if p not in whitelist:
                    _follow_links(p, whitelist)

        for p in site.getsitepackages():
            if os.path.isdir(p):
                if p not in whitelist:
                    _follow_links(p, whitelist)

        for white in whitelist:
            args.extend([
                f"--whitelist={white}",
                f"--read-only={white}",
            ])

        # Add files rules
        for rule in all_rules.file_rules:
            if isinstance(rule, BindRule):
                if rule.source == rule.dest:
                    if rule.source not in whitelist:
                        args.append(f"--whitelist={rule.source}")
                        whitelist.add(rule.source)
                else:
                    # Note: de py-sandbox manager the alias
                    if rule.source not in whitelist:
                        args.append(f"--whitelist={rule.source}")
                        whitelist.add(rule.source)
                    need_root = True
                    if not rule.write:
                        args.append(f"--read-only={rule.source}")
            elif isinstance(rule, IgnoreRule):
                args.append(f"--blacklist={rule.source}")

        if all_rules.socket_rules:
            # gw = get_default_gateway_info()
            # if gw:  # Initialize the gateway
            # FIXME: pour le dns, j'ai besoin de la gateway localhost
            # C'est bon si le dns est externe et non localhost
            # args.append(f"--defaultgw={gw[0]}")
            # Avec --net, il n'est plus possible de se connecter8 depuis le host
            # args.append(f"--net={gw[1]}")
            # pass

            net_filter4 = rule_to_netfilter(all_rules.socket_rules, is_ipv6=False)
            netfilter_file = tempfile.NamedTemporaryFile(mode='w+t',
                                                         delete=False,
                                                         # TODO: manager tmp file?
                                                         encoding='utf-8').name
            if DEBUG:
                netfilter_file = "netfilter.net"
                Path(netfilter_file).write_text("\n".join(net_filter4))
            args.append(f"--netfilter={netfilter_file}")

            net_filter6 = rule_to_netfilter(all_rules.socket_rules, is_ipv6=True)
            netfilter6_file = tempfile.NamedTemporaryFile(mode='w+t',
                                                          delete=False,
                                                          # TODO: manager tmp file?
                                                          encoding='utf-8').name
            if DEBUG:
                netfilter6_file = "netfilter6.net"
                Path(netfilter6_file).write_text("\n".join(net_filter6))
            args.append(f"--netfilter6={netfilter6_file}")

            # Remove redondant sockets rules
            socket_rules = []  # FIXME: Remove redondant sockets rules?

        # TODO: Add tmp rules
        # --tmpfs DEST

        # FIXME: use --env=name=value
        args.extend(["env", "-i"])
        for env, val in all_rules.envs.items():
            args.append(f"{env}={val}")

        if need_root:
            logger.warning("Firejail needs root to run")

        # FIXME: ajustement des rules pour firejail ?
        return args, all_rules

    def subprocess_cmd(self,
                       all_rules: AllRules,
                       envs: Envs,
                       ) -> List[str]:
        run_daemon = super().subprocess_cmd(envs, all_rules)

        cmd_parameters, _ = self._firejail_args(envs=envs,
                                                all_rules=all_rules)
        cmd_parameters.extend(run_daemon)
        # cmd_parameters.extend([
        #     sys.executable,
        #     "-P",
        #     # don't prepend a potentially unsafe path to sys.path; also PYTHONSAFEPATH
        #
        #     # "-u",  # FIXME unbuffered stdout and stderr
        #     "-m",
        #     run_daemon.__name__,
        # ])
        # verbose = return_level_parameter(log_level)
        # if verbose:
        #     cmd_parameters.append(verbose)
        # cmd_parameters.extend([
        #     "--outer-sandbox", "firejail",
        # ])
        if DEBUG:
            Path("run.sh").write_text("<.py-sandboxes " + " \\\n".join(cmd_parameters))
        return cmd_parameters

    def bash_args(self, envs: Envs) -> Args:
        args, _ = self._firejail_args(envs)
        args.extend([
            f"PS1={click.style('os-sandbox', fg='cyan')}]-firejail] $ ",
            # TODO: color ?
            # "PS1=[os-sandbox]\nfirejail $ ",
            "/bin/bash", "--norc", "--noprofile", "-i",
            # "wget", "-T", "1", "http://octo.com",  # FIXME
        ])
        return args, {}
