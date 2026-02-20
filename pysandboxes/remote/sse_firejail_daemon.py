import importlib
import logging
import os
import re
import shlex
import site
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterator, List, MutableSet, Optional, Set, Tuple, Union, cast

from ..all_rules import AllRules
from ..guard_files import BindRule, IgnoreRule
from ..netfilter import rule_to_netfilter
from ..sb_types import Args, ConfigLine, Envs
from ..tools import (
    Environ,
    follow_links_executable,
    remove_comments,
    substitute_env_vars,
)
from .sse_client_subprocess_daemon import BaseSubProcessDaemon
from .tools import suggest_package_installation, which_command

logger = logging.getLogger(__name__)

DEBUG = False

# Replace rules to delegate the filter to firejail.
# The exception are differents
REPLACE = True


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
        if not item.endswith("/"):
            item += "/"

        # Check if the item itself is in the set, or if an existing directory is
        # a prefix of the item. This means the item is a subdirectory of a
        # whitelisted path.
        for existing_dir in self._set:
            if item.startswith(existing_dir):
                return True

        return False

    def __iter__(self) -> Iterator[str]:
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
        if not directory.endswith("/"):
            directory += "/"

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
        if not directory.endswith("/"):
            directory += "/"
        self._set.discard(directory)


def _follow_links(filename: Union[str, Path], whitelist: WhiteList) -> None:
    whitelist.add(str(filename))
    try:
        if Path(filename).is_symlink():
            whitelist.add(str(Path(filename).resolve(strict=True)))
    except FileNotFoundError:
        raise RuntimeError(
            "Impossible to resolve the sys.executable `%s`", sys.executable
        )


class FireJailSSEDaemon(BaseSubProcessDaemon):
    def update_rules(
        self,
        *,
        all_rules: AllRules,
        envs: Envs,
    ) -> AllRules:
        _, updated_all_rules = self._firejail_args(all_rules, envs, None)
        return updated_all_rules

    def _firejail_args(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Optional[Path],
    ) -> Tuple[Args, AllRules]:
        """
        Apply the pysandboxes rules to firejail.
        """

        # Replace the rules.
        # The code never raise a RuleError
        if not which_command("firejail"):
            logger.error("firejail not found. Install it with:")
            logger.error(suggest_package_installation("firejail"))
            sys.exit(1)
        firejail_config = Path("/etc/firejail/firejail.config")
        restricted_network = True
        if firejail_config.exists():
            for line in firejail_config.read_text().split("\n"):
                if re.match(r"restricted-network\s+no", line):
                    restricted_network = False
                    break

        need_root = False
        args = [str(which_command("firejail"))]

        if logger.getEffectiveLevel() > logging.INFO:
            args.append("--quiet")
        else:
            logger.info(
                "Activate Firejail's output (to remove, "
                "change the level of this logger)"
            )

        # Add default parameters
        firejail_path = importlib.resources.files(__name__) / "firejail.profile"
        firejail_conf = remove_comments(firejail_path.read_text().splitlines())
        firejail_conf = substitute_env_vars(firejail_conf, envs)

        for line in firejail_conf:
            args.extend(shlex.split(line))

        # Extend mapping if the python version use some links
        major, minor, release_level, *_ = sys.version_info
        whitelist = WhiteList()

        # Manage sys.executable
        bin_path: Set[Path] = set()
        follow_links_executable(Path(sys.executable), bin_path)
        for p in bin_path:
            _follow_links(p, whitelist)

        for sp in sys.path:
            if os.path.isdir(sp):
                if sp not in whitelist:
                    _follow_links(sp, whitelist)

        for sp in site.getsitepackages():
            if os.path.isdir(sp):
                if sp not in whitelist:
                    _follow_links(p, whitelist)

        for white in whitelist:
            args.extend(
                [
                    f"--whitelist={white}",
                    f"--read-only={white}",
                ]
            )

        # Add ignore files rules
        keep_files_rules = []
        for rule in filter(lambda x: isinstance(x, IgnoreRule), all_rules.file_rules):
            args.append(f"--blacklist={rule.source}")
        for rule in sorted(
            filter(
                lambda x: isinstance(x, BindRule),
                all_rules.file_rules,
            ),
            key=lambda x: len(x.source),
        ):
            rule = cast(BindRule, rule)
            if rule.source == rule.dest:
                if rule.write or rule.source not in whitelist:
                    if rule.source != "/tmp/":
                        args.append(f"--whitelist={rule.source}")
                    whitelist.add(rule.source)
            else:
                # Note: py-sandbox manage the alias
                whitelist.add(rule.source)
                keep_files_rules.append(rule)
                need_root = False
            if not rule.write:
                args.append(f"--read-only={rule.source}")
            else:
                args.append(f"--read-write={rule.source}")

        if REPLACE:
            from ..guard_files import parse_rules as files_parse_rules

            _new_files_rules, _ = files_parse_rules(
                [ConfigLine("bind=/,/", Path(), 0)], []
            )
            new_files_rules = cast(List[BindRule], _new_files_rules)
            selected_rules = [
                rule
                for rule in all_rules.file_rules
                if isinstance(rule, BindRule) and rule.source != rule.dest
            ]
            selected_rules.extend(new_files_rules)  # Respect the order
            all_rules = all_rules._replace(file_rules=tuple(selected_rules))

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
                    repr(str(firejail_config)),
                )
                sys.exit(1)

            if pipe_path:  # Update rules?
                net_filter4 = rule_to_netfilter(all_rules.socket_rules, is_ipv6=False)
                netfilter_tmp_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".fifo"
                )
                netfilter_file = Path(netfilter_tmp_file.name)
                netfilter_tmp_file.close()
                netfilter_file.unlink(missing_ok=True)
                if DEBUG:
                    netfilter_file = Path("netfilter.net")
                else:
                    os.mkfifo(netfilter_file)

                def publich_netfilter() -> None:
                    netfilter_file.write_text("\n".join(net_filter4))
                    if not DEBUG:
                        netfilter_file.unlink(missing_ok=True)

                threading.Thread(target=publich_netfilter, daemon=True).start()

                args.append(f"--netfilter={netfilter_file}")

                net_filter6 = rule_to_netfilter(all_rules.socket_rules, is_ipv6=True)
                netfilter6_tmp_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".fifo"
                )
                netfilter6_file = Path(netfilter_tmp_file.name)
                netfilter6_tmp_file.close()
                netfilter6_file.unlink(missing_ok=True)
                if DEBUG:
                    netfilter6_file = Path("netfilter6.net")
                else:
                    os.mkfifo(netfilter6_file)

                def publich_netfilter6() -> None:
                    netfilter6_file.write_text("\n".join(net_filter6))
                    if not DEBUG:
                        netfilter_file.unlink(missing_ok=True)

                threading.Thread(target=publich_netfilter6, daemon=True).start()
                args.append(f"--netfilter6={netfilter6_file}")

            # Remove redondant sockets rules
            if REPLACE:
                from ..guard_socket import parse_rules as socket_parse_rules

                new_socket_rules, _ = socket_parse_rules(
                    [ConfigLine("net=ALLOW|*|*|*|*", Path(), 0)], []
                )
                all_rules = all_rules._replace(socket_rules=tuple(new_socket_rules))

            # Clean env variable
            args.extend(["env", "-i"])
            for env, val in all_rules.envs.items():
                args.append(f"{env}={val}")

            if need_root:
                logger.warning("Firejail needs root to run")

        return args, all_rules

    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
    ) -> List[str]:
        run_daemon_cmd = super().subprocess_cmd(
            all_rules,
            envs,
            pipe_path,
        )

        cmd_parameters, _ = self._firejail_args(
            all_rules=all_rules, envs=envs, pipe_path=pipe_path
        )
        cmd_parameters.extend(run_daemon_cmd)
        return cmd_parameters
