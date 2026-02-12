import importlib
import logging
import os
import re
import shlex
import site
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple, MutableSet, Any, Union, Dict, Optional

from .subprocess_daemon import BaseSubProcessDaemon
from .tools import which_command, suggest_package_installation
from ..all_rules import AllRules
from ..guard_files import BindRule, IgnoreRule
from ..netfilter import rule_to_netfilter
from ..sb_types import Envs, Args, ConfigLine
from ..tools import remove_comments, substitute_env_vars;

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

    def __init__(self) -> None:
        """
        Initializes the WhiteList with an optional list of directory paths.

        Args:
            directories (list[str]): A list of initial directory paths to add.
        """
        self._set: set[str] = set()

    def __contains__(self, item: Any) -> bool:
        """
        Checks if a directory path or any of its parent directories is in the WhiteList.

        Args:
            item (Any): The directory path to check.

        Returns:
            bool: True if the item is a string and is in the internal set or is a
                  sub-directory of an existing path, False otherwise.
        """

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
                     all_rules: AllRules,
                     envs: Envs,
                     ) -> AllRules:
        _, updated_all_rules = self._firejail_args(all_rules, envs, None)
        return updated_all_rules

    def _firejail_args(self,
                       all_rules: AllRules,
                       envs: Dict[str, str],
                       pipe_path: Optional[Path],
                       ) -> Tuple[Args, AllRules]:
        """
        Apply the pysandboxes rules to firejail.
        TODO: expliquer si on modifie
        """
        if not which_command("firejail"):
            logger.error("firejail not found. Install it with:")
            logger.error(suggest_package_installation("firejail"))
            sys.exit(1)
        firejail_config = Path("/etc/firejail/firejail.config")
        restricted_network = True
        if firejail_config.exists():
            for line in firejail_config.read_text().split("\n"):
                if re.match(r'restricted-network\s+no', line):
                    restricted_network = False
                    break

        need_root = False
        from importlib.resources import files

        args = [str(which_command("firejail"))]

        if logger.getEffectiveLevel() > logging.INFO:
            args.append("--quiet")
        else:
            logger.info("Activate Firejail's output (to remove, "
                        "change the level of this logger)")

        # Add default parameters
        firejail_path = importlib.resources.files(__name__) / 'firejail.profile'
        firejail_conf = remove_comments(firejail_path.read_text().splitlines())
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

        # Add ignore files rules
        keep_files_rules = []
        for rule in filter(lambda x: isinstance(x, IgnoreRule), all_rules.file_rules):
            args.append(f"--blacklist={rule.source}")
        for rule in sorted(
                filter(lambda x: isinstance(x, BindRule),
                       all_rules.file_rules,
                       ),
                key=lambda x: len(x.dest),
        ):
            if rule.source == rule.dest:
                if rule.write or rule.source not in whitelist:
                    args.append(f"--whitelist={rule.source}")
                    whitelist.add(rule.source)
            else:
                # Note: py-sandbox manage the alias
                if rule.source not in whitelist:  # FIXME
                    args.append(f"--whitelist={rule.source}")
                    whitelist.add(rule.source)
                    keep_files_rules.append(rule)
                    need_root = True
            if not rule.write:
                args.append(f"--read-only={rule.source}")
            else:
                args.append(f"--read-write={rule.source}")

        from ..guard_files import parse_rules as files_parse_rules
        new_files_rules, _ = files_parse_rules(
            [ConfigLine("bind=/,/", Path(), 0)], [])
        all_rules = all_rules._replace(file_rules=tuple(new_files_rules))

        # Add pipe_path rule
        # with --private-tmp, need more parameters
        if pipe_path:
            args.append(f"--mkdir={str(pipe_path)}")
            args.append(f"--whitelist={str(pipe_path)}")
            args.append(f"--read-only={str(pipe_path)}")

        if all_rules.socket_rules:
            if restricted_network:
                logger.error(
                    "Set 'restricted_network no' in %s "
                    "to use firejail with networks rules.",
                    repr(str(firejail_config)))
                sys.exit(1)

            if pipe_path:  # Update rules?
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
            from ..guard_socket import parse_rules as socket_parse_rules
            new_socket_rules, _ = socket_parse_rules(
                [ConfigLine("net=ALLOW|*|*|*|*", Path(), 0)], [])
            all_rules = all_rules._replace(socket_rules=tuple(new_socket_rules))

            # Clean env variable
            args.extend(["env", "-i"])
            for env, val in all_rules.envs.items():
                args.append(f"{env}={val}")

            if need_root:
                logger.warning("Firejail needs root to run")

        return args, all_rules

    def subprocess_cmd(self,
                       all_rules: AllRules,
                       envs: Dict[str, str],
                       pipe_path: Path,
                       ) -> List[str]:
        run_daemon_cmd = super().subprocess_cmd(
            all_rules,
            envs,
            pipe_path,
        )

        cmd_parameters, _ = self._firejail_args(
            all_rules=all_rules,
            envs=envs,
            pipe_path=pipe_path)
        cmd_parameters.extend(run_daemon_cmd)
        return cmd_parameters
