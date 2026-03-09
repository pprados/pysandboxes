# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""File system access guard for PySandboxes.

This module implements comprehensive file system sandboxing by intercepting and
controlling access to files and directories. It provides a whitelist-based security
model with support for ignore patterns, bind mounts, and access logging.

The guard patches standard library functions like open(), Path operations, and
directory scanning to enforce security rules defined in the configuration.
"""

import fnmatch
import functools
import io
import logging
import os
import sys
from collections import OrderedDict
from errno import ENOENT
from os import PathLike
from os import scandir as _scandir
from pathlib import Path as Path
from types import ModuleType, TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    Iterator,
    NamedTuple,
    NoReturn,
    Type,
    TypeAlias,
    cast,
)

from .config import OPTIMIZE
from .e import RuleFileNotFoundError, RulePermissionError
from .guard_envs import LearnEnviron
from .learning import add_learning_rule, is_learning_mode
from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLine, ConfigLines
from .tools import follow_links_executable

if io or os:
    pass

if TYPE_CHECKING:
    import pathlib

_Path_glob = Path.glob
_Path_rglob = Path.rglob

logger = logging.getLogger(__name__)

_white_list = [
    "<frozen posixpath>",
    "<frozen genericpath>",
]

StrOrBytesPath: TypeAlias = (
    str | bytes | os.PathLike[str] | os.PathLike[bytes]
)  # stable


# Internal representation of a rule
class BindRule(NamedTuple):
    """File system bind mount rule.

    Attributes:
        source: Source path on host system.
        dest: Destination path in sandbox (None for same as source).
        write: Whether write access is allowed.
        config: Configuration line where rule was defined.
    """

    source: str
    dest: str | None
    write: bool
    config: ConfigLine


class IgnoreRule(NamedTuple):
    """File system ignore rule.

    Attributes:
        source: Glob pattern for files to ignore.
        config: Configuration line where rule was defined.
    """

    source: str
    config: ConfigLine


FilesRule = BindRule | IgnoreRule

FileRules = tuple[FilesRule, ...]


class LearnFileRule(NamedTuple):
    """File access observed during learning mode.

    Attributes:
        path: File or directory path that was accessed.
        write: Whether write access was attempted.
    """

    path: "pathlib.Path"
    write: bool


class _DirEntry:
    def __init__(self, target: Any, path: str) -> None:
        super()
        # self._target = target
        # self._path = path

        super().__setattr__("_target", target)
        super().__setattr__("_path", path)

    def __getattr__(self, name: str) -> Any:
        # Called only if attribute not found the usual way
        if name == "path":
            return self._path
        return getattr(self._target, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target, name, value)


# Internal state for the file filter
_rules: FileRules = cast(FileRules, ())

_os_path_realpath = os.path.realpath
_os_path_abspath = os.path.abspath


def parse_rules(
    config: ConfigLines,
    errors: list[ErrorMsg],
) -> tuple[FileRules, ConfigLines]:
    """Parse file system access rules from configuration.

    Supports bind=src,dest and ignore=glob_pattern rules.

    Args:
        config: Configuration lines to parse.
        errors: List to collect parsing errors.

    Returns:
        Tuple of parsed file rules and remaining config lines.
    """
    """
    Parses rule strings into internal ParserRule objects.
    Supports --bind=src,dest and --ignore=glob_pattern.
    """
    rules_ignore: list[FilesRule] = []
    rules_bind: list[BindRule] = []
    ignore_rules: ConfigLines = []
    for rule in config:
        if rule.rule.startswith("bind=") or rule.rule.startswith("ro-bind="):
            value = rule.rule.split("=", 1)[1]
            try:
                s_src, s_dest = value.split(",", 1)
                if not s_src and not s_dest:
                    continue  # Ignore empty bind
                if s_src and s_dest:
                    src = Path(Path(s_src).expanduser()).resolve().absolute()
                    dest = Path(Path(s_dest).expanduser()).resolve().absolute()
                    if not src.is_dir() or not dest.is_dir():
                        cwd = Path.cwd()
                        if src.is_relative_to(cwd):
                            s_src = str(src.relative_to(cwd))
                        else:
                            s_src = str(src)
                        if dest.is_relative_to(cwd):
                            s_dest = str(dest.relative_to(cwd))
                        else:
                            s_dest = str(dest)
                        errors.append(
                            (
                                f"{format_ruleref(rule)}: "
                                f"In 'bind={s_src},{s_dest}', "
                                f"source and destination must exists "
                                f"and must be directories.",
                                rule.path,
                                rule.ln,
                            )
                        )
                        continue
                    # Search same file_rules with different write flag
                    is_write = rule.rule.startswith("bind=")
                    for bind_rule in rules_bind:
                        if bind_rule.source == src and bind_rule.dest == dest:
                            if bind_rule.write != is_write:
                                errors.append(
                                    (
                                        f"{format_ruleref(rule)}: "
                                        f"In {rule.rule!r}, "
                                        f"invalidate another rule "
                                        f"from {format_ruleref(bind_rule.config)!r}.",
                                        rule.path,
                                        rule.ln,
                                    )
                                )
                            else:
                                # Detect duplicate bind rule
                                break
                    else:
                        # Only one last "/"
                        src_str = str(Path(src)) + "/" if src != Path("/") else "/"
                        dest_str = str(Path(dest)) + "/" if dest != Path("/") else "/"
                        rules_bind.append(
                            BindRule(
                                source=src_str,
                                dest=dest_str,
                                write=rule.rule.startswith("bind="),
                                config=rule,
                            )
                        )
                else:
                    errors.append(
                        (
                            f"{format_ruleref(rule)}: "
                            f"In {rule.rule!r}, "
                            f" source and destination must be set",
                            rule.path,
                            rule.ln,
                        )
                    )
                    continue

            except ValueError:
                errors.append(
                    (
                        f"{format_ruleref(rule)}: "
                        f"In {rule.rule!r}, "
                        f"source and destination must be separated with a comma.",
                        rule.path,
                        rule.ln,
                    )
                )
                continue
        elif rule.rule.startswith("ignore="):
            pattern = rule.rule[len("ignore=") :]
            rules_ignore.append(IgnoreRule(pattern, rule))
        else:
            ignore_rules.append(rule)

    # Add path for python
    list_bin = list(follow_links_executable(Path(sys.executable), set()))
    for p in list_bin:
        rules_bind.append(
            BindRule(
                source=str(p),
                dest=str(p),
                write=False,
                config=ConfigLine("<python>", Path(), 0),
            )
        )
    rules_bind = sorted(
        rules_bind, key=lambda r: len(r.dest) if r.dest else 0, reverse=True
    )

    return tuple(rules_ignore + cast(list[FilesRule], rules_bind)), ignore_rules


def _check_is_in_rules(path: Path) -> bool:
    """Check if path is covered by existing rules.

    Args:
        path: Path to check.

    Returns:
        True if path is covered by rules, False otherwise.
    """
    global _rules
    spath = str(path) + "/"
    for rule in _rules:
        if isinstance(rule, BindRule):
            if spath == rule.source:
                return True
    return False


_learn_env = LearnEnviron()

_special_env = OrderedDict(
    sorted(
        (
            (k, _learn_env._get(k))
            for k in [
                "PWD",
                "HOME",
                "TMP",
                "TEMP",
            ]
            if _learn_env._has(k)
        ),
        key=lambda x: len(x[1]),
        reverse=True,
    )
)

_special_home = OrderedDict(
    sorted(
        (
            (k, _learn_env._get(k))
            for k in [
                "PYENV_ROOT",
                "VIRTUAL_ENV",
                "CONDA_HOME",
                "HF_HOME",
                "HF_DATASETS_CACHE",
                "HF_MODULES_CACHE",
                "HF_HUB_CACHE",
                "TRANSFORMERS_CACHE" "," "TORCH_HOME",
                "KERAS_HOME",
                "TFHUB_CACHE_DIR",
                "MXNET_HOME",
                "NLTK_DATA",
                "SPACY_DATA",
            ]
            if _learn_env._has(k)
        ),
        key=lambda x: len(x[1]),
        reverse=True,
    )
)


def generate_rules(
    learn: set[Any],
) -> list[str]:
    """Generate file system rules from learning data.

    Creates bind and ignore rules based on observed file access
    during learning mode execution.

    Args:
        learn: Set of learned file access patterns.

    Returns:
        List of bind= and ignore= configuration rule strings.
    """
    # Select only parent
    global _special_env, _special_home
    learn = learn.copy()
    parent_level: dict[Path, bool] = {}
    list_bin = list(follow_links_executable(Path(sys.executable), set()))
    for learn_rule in filter(lambda x: isinstance(x, LearnFileRule), learn):
        parent = learn_rule.path.absolute()
        for bin_path in list_bin:
            if parent.is_relative_to(bin_path):
                break
        else:
            # logger.debug("Generate rule for %s", learn_rule.path)
            if not parent.is_dir():
                parent = parent.parent
            if not parent_level.get(parent, False) and learn_rule.write:
                parent_level[parent] = True
            else:
                parent_level[parent] = parent_level.get(parent, False)

    result: set[str] = set()
    home = Path.home().absolute()

    allready_added: list[LearnFileRule] = []
    for path in sorted(parent_level.keys()):
        if (
            path.exists()
            and (path.is_file() or path.is_dir())
            and os.access(path, os.R_OK)
        ):
            write = parent_level[path]
            value = None
            overflow = False
            for allready_path, allready_write in allready_added:
                if allready_path == home:
                    continue
                if path.is_relative_to(allready_path):
                    if write == allready_write:
                        overflow = True
                        break
            if overflow:
                continue

            for key, val in _special_home.items():
                if path.is_relative_to(val):
                    value = f"${{{key}}}"
                    break
            else:
                for key, val in _special_env.items():
                    if path.is_relative_to(val):
                        if not _check_is_in_rules(path):
                            x = "/" + str(path.relative_to(val))
                            if x == "/.":
                                x = ""
                            if key == "PWD":
                                value = "." + x
                            elif key == "HOME":
                                value = "~" + x
                            else:
                                value = f"${{{key}}}" + x
                        break
            if not value:
                value = str(path)
            if value and value != "${HOME}":
                result.add("" + f'{"" if write else "ro-"}bind={value},{value}')
            if path != home:
                allready_added.append(LearnFileRule(path, write))
    return sorted(list(result))


def _apply_ignore_rule(path: str | os.PathLike) -> tuple[str | None, FilesRule | None]:
    for rule in _rules:
        if isinstance(rule, IgnoreRule):
            assert rule.source is not None
            if fnmatch.fnmatch(Path(path).name, rule.source):
                return None, rule
    return str(path), None


# Helper to resolve symlinks and apply rules
def _apply_src_to_dest_rules(
    path: str, accept_src: bool = False, accept_dest: bool = False
) -> tuple[str | None, FilesRule | None]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    real_path = _os_path_abspath(os.path.normpath(path))
    # if path.endswith("/"):
    #     real_path = real_path + "/"
    original_path = path

    for rule in _rules:
        if isinstance(rule, BindRule):
            assert rule.source is not None
            assert rule.dest is not None
            if (
                rule.source != rule.dest
                and (real_path.startswith(rule.dest) or real_path == rule.dest[:-1])
                and not accept_dest
            ):
                return None, rule
            if (
                rule.source != rule.dest
                and real_path == rule.source[:-1]
                and not accept_src
            ):
                return None, rule
            if real_path.startswith(rule.source) or real_path == rule.source[:-1]:
                if (
                    rule.source != rule.dest
                    and not accept_dest
                    and real_path == rule.dest[:-1]
                ):
                    return None, rule
                relative = os.path.relpath(real_path, rule.source)
                if relative != ".":
                    new_path = os.path.join(rule.dest, relative)
                else:
                    new_path = rule.dest
                    if not path.endswith("/"):
                        new_path = new_path[:-1]

                return new_path, None
        elif isinstance(rule, IgnoreRule):
            if fnmatch.fnmatch(original_path, rule.source) or fnmatch.fnmatch(
                real_path, rule.source
            ):
                return None, rule
        else:
            assert "Invalid rules"
    return path, None


# Helper to resolve symlinks and apply rules
def _apply_dest_to_src_rules(
    path: str | os.PathLike | _DirEntry,
    *,
    write: bool,
    accept_src: bool = False,
    accept_dest: bool = True,
) -> tuple[str | None, FilesRule | None]:
    """
    Change destination file, ask by the program, to the real source file.
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """

    if not path:
        return None, None
    if isinstance(path, _DirEntry):  # FIXME: a vérifier
        path = path.path
    fake_path = _os_path_abspath(path)
    if str(path).endswith("/"):
        fake_path = fake_path + "/"
    original_path = path

    for rule in _rules:
        if isinstance(rule, BindRule):
            if rule.source is None or rule.dest is None:
                continue
            if (
                rule.source != rule.dest
                and str(fake_path).startswith(rule.dest[:-1])
                and not accept_dest
            ):
                return None, rule
            if rule.source != rule.dest and fake_path.startswith(rule.source[:-1]):
                if not accept_src:
                    return None, rule
                relative = fake_path[len(rule.source) :]
                new_path = os.path.join(rule.dest, relative)
                if not fake_path.endswith("/") and relative == "":
                    new_path = new_path[:-1]
                return new_path, None

            if fake_path.startswith(rule.dest) or fake_path == rule.dest[:-1]:
                if fake_path == rule.dest[:-1]:
                    fake_path_dir = rule.dest
                else:
                    fake_path_dir = fake_path
                if not rule.write and write:
                    if is_learning_mode():
                        add_learning_rule(LearnFileRule(Path(path), True))
                    else:
                        raise RulePermissionError(
                            f"Cannot write to {rule.dest!r}. "
                            f"Rule {rule.config.rule!r} from "
                            f"{format_ruleref(rule.config)}"
                        )
                relative = os.path.relpath(fake_path_dir, rule.dest)
                if relative == ".":
                    relative = ""
                new_path = os.path.join(rule.source, relative)
                if not fake_path.endswith("/") and relative == "":
                    new_path = new_path[:-1]
                return new_path, None
        elif isinstance(rule, IgnoreRule):
            assert rule.source is not None
            if rule.source[0] == "/":
                if fnmatch.fnmatch(str(original_path), rule.source) or fnmatch.fnmatch(
                    fake_path, rule.source
                ):
                    return None, rule
            else:
                if fnmatch.fnmatch(
                    Path(original_path).name, rule.source
                ) or fnmatch.fnmatch(Path(fake_path).name, rule.source):
                    return None, rule
        else:
            assert False, f"Invalid guard_files rules {type(rule)=}"  # noqa: B011
    return None, None


def _raise_ignore(file: str | bytes | os.PathLike | int, rule: FilesRule) -> NoReturn:
    assert rule is not None

    ex = RuleFileNotFoundError(
        f"Access to {file!r} is ignored by "
        f"rule {rule.config.rule!r} from {format_ruleref(rule.config)}"
    )
    ex.errno = ENOENT
    raise ex


def _raise_access(file: str) -> NoReturn:
    path = Path(file)
    try:
        f = str(path.absolute())
    except ValueError:
        f = str(path)
    ex = RuleFileNotFoundError(f"Access to {f}' must be accepted by a rule.")
    ex.errno = ENOENT
    raise ex


# %% Generic wrapper
# def _wrap_empty(func: Callable) -> Callable:
#     return func


# def _wrap_reload_module(func: Callable, *, name: str) -> ModuleType:
#     # Use _f(_wrap_reload_module, name="io") to refresh a module in another module
#     import sys
#     return sys.modules[name]


def _wrap_buitins_open(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
        file: str | None,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Callable | None = None,
    ) -> Any:

        need_to_write = mode is not None and (
            "w" in mode or "a" in mode or "x" in mode or "+" in mode
        )
        if file:
            remapped, rule = _apply_dest_to_src_rules(file, write=need_to_write)
            if rule:
                _raise_ignore(file, rule)
            if not remapped:
                if is_learning_mode():
                    add_learning_rule(LearnFileRule(Path(file), write=need_to_write))
                    remapped = file
                else:
                    _raise_access(file)
        else:
            remapped = None
        return func(
            remapped,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
            closefd=closefd,
            opener=opener,
        )

    return wrapper


# def _wrap_test(func: Callable) -> Callable:  # FIXME
#     @functools.wraps(func)
#     def wrapper(
#             *args,**kwargs
#     ) -> Any:
#         return func(*args, **kwargs)
#
#     return wrapper
#


def _wrap_filename(func: Callable, *, write: bool, learn: bool = True) -> Callable:
    @functools.wraps(func)
    def wrapper(
        file: str | bytes | os.PathLike | int, *args: Any, **kwargs: dict[str, Any]
    ) -> Any:

        # Detect call from posixpath
        if isinstance(file, int):
            return func(file, *args, **kwargs)
        if isinstance(file, _DirEntry):
            file = file.path
        if isinstance(file, bytes):
            file = os.fsdecode(file)
        file = cast(str, file)
        remapped, rule = _apply_dest_to_src_rules(cast(str, file), write=write)
        if rule:
            _raise_ignore(file, rule)
        if not remapped:
            if is_learning_mode():
                if learn:
                    add_learning_rule(LearnFileRule(Path(file), write))
                remapped = file
            else:
                _raise_access(file)
        return func(remapped, *args, **kwargs)

    return wrapper


def _wrap_two_filenames(
    func: Callable, *, in_write: bool = False, out_write: bool = True
) -> Callable:
    @functools.wraps(func)
    def wrapper(
        src: str | bytes | os.PathLike,
        dest: str | bytes | os.PathLike,
        *args: Any,
        **kwargs: dict[str, Any],
    ) -> Any:
        # Detect call from posixpath
        if isinstance(src, _DirEntry):
            src = src.path
        if isinstance(src, bytes):
            src = os.fsdecode(src)
        if isinstance(dest, _DirEntry):
            dest = dest.path
        if isinstance(dest, bytes):
            dest = os.fsdecode(dest)
        src = cast(str, src)
        dest = cast(str, dest)
        remapped_src, rule1 = _apply_dest_to_src_rules(cast(str, src), write=in_write)
        if rule1:
            _raise_ignore(src, rule1)
        remapped_dest, rule2 = _apply_dest_to_src_rules(
            cast(str, dest), write=out_write
        )
        if rule2:
            _raise_ignore(dest, rule2)
        if remapped_src is None and rule1 is not None:
            _raise_ignore(src, rule1)
        if remapped_src is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(src), in_write))
                remapped_src = src
            else:
                _raise_access(src)

        if remapped_dest is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(dest), out_write))
                remapped_dest = dest
            else:
                _raise_access(dest)

        return func(str(remapped_src), str(remapped_dest), *args, **kwargs)

    return wrapper


def _wrap_os_path_realpath(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: str | bytes | os.PathLike) -> Any:
        # Detect call from posixpath
        file = cast(str, file)
        remapped, rule = _apply_dest_to_src_rules(cast(str, file), write=False)
        if rule:
            _raise_ignore(file, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file), write))
                remapped = file
                pass
            else:
                _raise_access(file)
        return func(remapped)

    return wrapper


def _wrap_os_stat(func: Callable, *, write: bool) -> Callable:
    @functools.wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike | int,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> Any:
        if isinstance(path, int):
            return func(path=path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        remapped, rule = _apply_dest_to_src_rules(cast(str, path), write=write)
        if rule:
            _raise_ignore(path, rule)
        if not remapped:
            if is_learning_mode():
                # add_learning_rule(LearnFileRule(Path(path), write))
                remapped = path
            else:
                _raise_access(path)
        return func(path=remapped, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    return wrapper


def _wrap_os_path_samefile(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
        f1: str | bytes | os.PathLike,
        f2: str | bytes | os.PathLike,
    ) -> Any:
        if isinstance(f1, int) or isinstance(f2, int):
            return func(f1, f2)
        if isinstance(f1, bytes):
            f1 = os.fsdecode(f1)
        if isinstance(f2, bytes):
            f2 = os.fsdecode(f2)
        f1 = cast(str, f1)
        f2 = cast(str, f2)
        # Detect call from posixpath
        remapped_src, rule1 = _apply_dest_to_src_rules(cast(str, f1), write=False)
        if rule1:
            _raise_ignore(f1, rule1)
        remapped_dest = None
        if remapped_src is not None:
            remapped_dest, rule2 = _apply_dest_to_src_rules(cast(str, f2), write=False)
            if rule2:
                _raise_ignore(f2, rule2)
        if remapped_dest is None:
            remapped_dest = f2
        return func(str(remapped_src), str(remapped_dest))

    return wrapper


def _wrap_os_chdir(func: Callable, *, write: bool) -> Callable:
    @functools.wraps(func)
    def wrapper(path: str | bytes | os.PathLike | int) -> None:

        # Detect call from posixpath
        if isinstance(path, int):
            return func(path)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)

        if isinstance(path, int):
            return func(path)
        new_dir = cast(str, os.fspath(path))
        if not new_dir.endswith("/"):
            new_dir = new_dir + "/"
        remapped, rule = _apply_dest_to_src_rules(new_dir, write=write)
        if rule:
            _raise_ignore(path, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(path), write))
                remapped = path
            else:
                _raise_access(path)
        return func(remapped)

    return wrapper


def _wrap_pathlib_Path_glob(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
        self: Any,
        pattern: str,
        *,
        case_sensitive: bool | None = None,
        recurse_symlinks: bool = False,
    ) -> Iterator["Path"]:

        remapped, rule = _apply_dest_to_src_rules(self, write=False)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(self, write=False))
                remapped = self
            else:
                _raise_access(self)

        def filter(it: Iterator[Path]) -> Iterator[Path]:
            abs_remapper = _os_path_realpath(remapped)
            for name in it:
                remapped_filter, rule = _apply_src_to_dest_rules(
                    str(name), accept_src=False, accept_dest=True
                )
                if remapped_filter:
                    if not str(self).startswith("/"):
                        remapped_filter = remapped_filter[len(abs_remapper) + 1 :]
                    if remapped_filter == "":
                        remapped_filter = "."
                    # yield Path(remapped_filter).relative_to(self)
                    yield Path(remapped_filter)

        do_filter = filter(
            func(
                Path(remapped),
                pattern=pattern,
                case_sensitive=case_sensitive,
                recurse_symlinks=recurse_symlinks,
            )
        )
        return do_filter

    return wrapper


# %% os wrapper
def _wrap_os_open(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike | int,
        flags: int,
        mode: int = 0x777,
        *,
        dir_fd: int | None = None,
    ) -> int:

        if isinstance(path, int):
            return func(path=path, flags=flags, mode=mode, dir_fd=dir_fd)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        # Detect call from posixpath
        if isinstance(path, int):
            return func(path=path, flags=flags, mode=mode, dir_fd=dir_fd)
        if dir_fd is not None:
            remapped, rule = _apply_ignore_rule(path)
            if rule:
                _raise_ignore(path, rule)
            return func(path=remapped, flags=flags, mode=mode, dir_fd=dir_fd)
        if isinstance(path, _DirEntry):  # FIXME: vérifier si nécessaire
            path = path.path
        path = cast(str, path)
        if isinstance(flags, int):
            need_to_write = bool(
                (flags & os.O_WRONLY) or (flags & os.O_RDWR) or (flags & os.O_APPEND)
            )
            remapped, rule = _apply_dest_to_src_rules(path, write=need_to_write)
            if remapped is None:
                if is_learning_mode():
                    add_learning_rule(LearnFileRule(Path(path), False))
                    remapped = path
                else:
                    _raise_access(path)
        return func(path=remapped, flags=flags, mode=mode, dir_fd=dir_fd)

    return wrapper


def _wrap_os_access(func: Callable, *, write: bool) -> Callable:
    @functools.wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike | int,
        mode: int,
        *,
        dir_fd: int | None = None,
        effective_ids: bool = False,
        follow_symlinks: bool = True,
    ) -> bool:
        if isinstance(path, int):
            return func(
                path=path,
                mode=mode,
                dir_fd=dir_fd,
                effective_ids=effective_ids,
                follow_symlinks=follow_symlinks,
            )
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        # Detect call from posixpath
        if isinstance(path, int):
            return func(
                path=path,
                mode=mode,
                dir_fd=dir_fd,
                effective_ids=effective_ids,
                follow_symlinks=follow_symlinks,
            )
        if isinstance(path, _DirEntry):
            path = path.path
        path = cast(str, path)
        remapped, rule = _apply_dest_to_src_rules(path, write=write)
        if rule:
            return False
        if not remapped:
            remapped = path
        if is_learning_mode():
            # add_learning_rule(LearnFileRule(Path(file), False))
            remapped = path
        return func(
            path=remapped,
            mode=mode,
            dir_fd=dir_fd,
            effective_ids=effective_ids,
            follow_symlinks=follow_symlinks,
        )

    return wrapper


def _wrap_os_getcwd(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper() -> str:
        # Detect call from posixpath
        dir: str = func()
        new_dir = os.fsdecode(os.fspath(dir))
        if not new_dir.endswith("/"):
            new_dir = new_dir + "/"

        remapped, rule = _apply_src_to_dest_rules(new_dir, accept_src=True)
        if remapped is None:
            if is_learning_mode():
                # add_learning_rule(LearnFileRule(Path(new_dir), False))
                remapped = new_dir
            else:
                _raise_access(new_dir)

        if remapped.endswith(os.path.sep + "."):
            remapped = remapped[:-2]
        if remapped.endswith(os.path.sep):
            remapped = remapped[:-1]
        return str(remapped)

    return wrapper


def _wrap_os_getcwdb(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper() -> bytes:
        # Detect call from posixpath
        dir = func()
        new_dir = os.fspath(dir.decode())
        if not new_dir.endswith("/"):
            new_dir = new_dir + "/"

        remapped, rule = _apply_src_to_dest_rules(new_dir, accept_dest=True)
        if remapped is None:
            if is_learning_mode():
                # add_learning_rule(LearnFileRule(Path(new_dir), False))
                remapped = new_dir
            else:
                _raise_access(new_dir)
        if remapped.endswith(os.path.sep + "."):
            remapped = remapped[:-2]
        if remapped.endswith(os.path.sep):
            remapped = remapped[:-1]
        if remapped == new_dir:
            return dir
        return str(remapped).encode(sys.getfilesystemencoding())

    return wrapper


def _wrap_os_listdir(func: Callable[..., list[str]]) -> Callable[..., list[str]]:
    @functools.wraps(func)
    def wrapper(path: str | os.PathLike | bytes | int | None = None) -> list[str]:

        if isinstance(path, int):
            return func(path=path)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if path is None:
            path = "."
        path = cast(str, path)
        if new_path_and_rule := _apply_dest_to_src_rules(
            path, write=False, accept_src=False, accept_dest=True
        ):
            remapped, rule = new_path_and_rule
            if rule:
                _raise_ignore(path, rule)
            if remapped is None:
                if is_learning_mode():
                    add_learning_rule(LearnFileRule(Path(path), False))
                    remapped = path
                else:
                    _raise_access(path)
            entries = func(remapped)
            if not is_learning_mode():
                filtered: list[str] = []
                for entry in entries:
                    full_path = os.path.join(path, entry)
                    remapped_file, _ = _apply_dest_to_src_rules(
                        full_path, write=False, accept_dest=True
                    )
                    if remapped_file and remapped_file not in filtered:
                        filtered.append(entry)
                return filtered
            else:
                return entries
        else:
            return []

    return wrapper


def _wrap_os_readlink(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(path: str | bytes | os.PathLike, *, dir_fd: int | None = None) -> str:

        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        remapped_first, rule = _apply_dest_to_src_rules(cast(str, path), write=False)
        if rule:
            _raise_ignore(path, rule)
        if not remapped_first:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(path), False))
            remapped_first = path
        remapped = func(path=remapped_first, dir_fd=dir_fd)
        if not remapped.startswith(os.path.sep):
            remapped = os.path.dirname(remapped_first) + os.path.sep + remapped
        remapped, rule = _apply_src_to_dest_rules(remapped)
        if rule:
            _raise_ignore(path, rule)
        elif not remapped:
            _raise_access(path)
        return remapped

    return wrapper


def _wrap_os_symlink(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
        src: StrOrBytesPath,
        dst: StrOrBytesPath,
        target_is_directory: bool = False,
        *,
        dir_fd: int | None = None,
    ) -> Any:

        if isinstance(str, int) or isinstance(dst, int):
            return func(
                src=src,
                dst=dst,
                target_is_directory=target_is_directory,
                dir_fd=dir_fd,
            )
        if isinstance(src, bytes):
            src = os.fsdecode(src)
        if isinstance(dst, bytes):
            src = os.fsdecode(dst)
        src = cast(str, src)
        dst = cast(str, dst)
        remapped, rule = _apply_dest_to_src_rules(cast(str, dst), write=True)
        if rule:
            _raise_ignore(dst, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(dst), False))
                remapped = dst
            else:
                _raise_access(dst)
        if str(src).startswith("/"):
            remapped_src, _ = _apply_dest_to_src_rules(
                src, write=False, accept_src=True
            )
        else:
            remapped_src = src  # Relative link

        return func(
            remapped_src,
            remapped,
            target_is_directory=target_is_directory,
            dir_fd=dir_fd,
        )

    return wrapper


def _wrap_os_unlink(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(path: StrOrBytesPath, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            return func(path=path, dir_fd=dir_fd)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        remapped, rule = _apply_dest_to_src_rules(cast(str, path), write=False)
        if rule:
            _raise_ignore(path, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(path), True))
                remapped = path
            else:
                _raise_access(path)
        return func(path=remapped, dir_fd=dir_fd)

    return wrapper


def _wrap_os_rmdir(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(path: StrOrBytesPath, *, dir_fd: int | None = None) -> None:
        if dir_fd is not None:
            return func(path=path, dir_fd=dir_fd)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        remapped, rule = _apply_dest_to_src_rules(cast(str, path), write=False)
        if rule:
            _raise_ignore(path, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(path), True))
                remapped = path
            else:
                _raise_access(path)
        return func(path=remapped, dir_fd=dir_fd)

    return wrapper


class _ScanDirContextManager(Iterator):
    """
    A context manager that wraps os.scandir and implements the context manager kind.
    """

    __slot__ = ("directory", "real_directory", "scanner")

    def __init__(self, directory: str):
        self.directory = directory
        new_path, rule = _apply_dest_to_src_rules(directory, write=False)
        if rule:
            _raise_ignore(directory, rule)
        if new_path is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(directory).absolute(), False))
                new_path = directory
            else:
                _raise_access(directory)
        self.real_directory = new_path
        self.scanner: ContextManager | Iterator | None = None

    def close(self) -> None:
        if self.scanner and hasattr(self.scanner, "close"):
            self.scanner.close()

    def __enter__(self) -> "_ScanDirContextManager":
        """
        Enter the context manager, opening the scandir iterator.
        """
        self.scanner = _scandir(self.real_directory)
        self.scanner.__enter__()
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Any:
        """
        Exit the context manager, closing the scandir iterator.
        """
        if self.scanner is not None:
            return cast(ContextManager, self.scanner).__exit__(
                exc_type, exc_val, exc_tb
            )
        return False  # Don't suppress exceptions

    def __iter__(self) -> Iterator[str]:
        """h
        Make the context manager iterable.
        """
        if is_learning_mode() and OPTIMIZE:
            return cast(Iterator, self.scanner).__iter__()  # type: ignore[union-attr]
        return self

    def __next__(self) -> os.DirEntry:
        """
        Get the next file entry from the directory.
        """
        if self.scanner is None:
            raise StopIteration

        if not self.real_directory:
            raise StopIteration

        while True:
            try:
                while True:
                    entry = cast(Iterator, self.scanner).__next__()
                    dest_path, rule = _apply_src_to_dest_rules(
                        entry.path, accept_src=False, accept_dest=True
                    )
                    if rule:
                        pass  # Ignore
                    elif dest_path is not None:
                        _entry = _DirEntry(entry, dest_path)
                        return cast(os.DirEntry, _entry)
            except StopIteration:
                raise


def _wrap_os_scandir(func: Callable) -> Callable:
    """
    Wrap os.scandir to handle exceptions and return an iterator or None.
    """

    @functools.wraps(func)
    def wrapper(path: str | bytes | os.PathLike | None = None) -> Iterator:
        if path is None:
            path = "."
        if isinstance(path, int):
            return func(path)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        return _ScanDirContextManager(path)

    return wrapper


# %% io wrapper


def _wrap_io_open(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
        file: str | bytes | os.PathLike | int,
        mode: str | None = "r",
        buffering: int | None = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Callable | None = None,
    ) -> Any:

        # Detect call from posixpath
        if mode is None:
            mode = "r"
        if isinstance(file, int):
            return func(
                file=file,
                mode=mode,
                buffering=buffering,
                encoding=encoding,
                errors=errors,
                newline=newline,
                closefd=closefd,
                opener=opener,
            )
        if isinstance(file, _DirEntry):  # FIXME: validate
            file = file.path
        if isinstance(file, bytes):
            file = os.fsdecode(file)
        file = str(file)
        need_to_write = mode is not None and (
            "w" in mode or "a" in mode or "x" in mode or "+" in mode
        )
        remapped, rule = _apply_dest_to_src_rules(file, write=need_to_write)
        if rule:
            _raise_ignore(file, rule)
        if remapped is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file).absolute(), need_to_write))
                remapped = file
            else:
                _raise_access(file)
        return func(
            file=remapped,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
            closefd=closefd,
            opener=opener,
        )

    return wrapper


def _wrap_io_FileIO(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
        file: str | bytes | os.PathLike | int,
        mode: str | None = "r",
        closefd: bool = True,
        opener: Callable | None = None,
    ) -> Any:

        # Detect call from posixpath
        if mode is None:
            mode = "r"
        if isinstance(file, int):
            return func(
                file=file,
                mode=mode,
                closefd=closefd,
                opener=opener,
            )
        # if isinstance(name, _DirEntry):
        #     file = file.path
        if isinstance(file, bytes):
            name = os.fsdecode(file)
        file = str(file)
        need_to_write = mode is not None and (
            "w" in mode or "a" in mode or "x" in mode or "+" in mode
        )
        remapped, rule = _apply_dest_to_src_rules(file, write=need_to_write)
        if rule:
            _raise_ignore(file, rule)
        if remapped is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file).absolute(), need_to_write))
                remapped = name
            else:
                _raise_access(file)
        return func(
            file=remapped,
            mode=mode,
            closefd=closefd,
            opener=opener,
        )

    return wrapper


# %% _os
def _wrap__os(module: ModuleType) -> ModuleType:
    # if "os" in sys.modules:
    #     del sys.modules["os"]  # FIXME: pourquoi del sur ce module ? Et io ?
    import os

    assert os.open.__pysandbox__  # type: ignore[attr-defined]
    return os


def _wrap__io(module: ModuleType) -> ModuleType:
    if "io" in sys.modules:
        del sys.modules["io"]
    import io

    assert io.open.__pysandbox__  # type: ignore [attr-defined]
    return io


# Wrapper for factory to wrapper ;-)
def _f(func: Callable, **kwargs: Any) -> Callable:
    def wrapper() -> Any:
        def wrapper2(original: Any) -> Any:
            return func(original, **kwargs)

        wrapper2.__doc__ = func.__doc__
        return wrapper2

    return wrapper()


_default_rules: dict[str, Callable] = {
    "os.chdir": _f(_wrap_os_chdir, write=False),
    # ALLOW os.fchdir
    "os.getcwd": _f(_wrap_os_getcwd),
    "os.getcwdb": _f(_wrap_os_getcwdb),
    # ALLOW os.fdopen
    "os.open": _f(_wrap_os_open),
    "os.access": _f(_wrap_os_access, write=False),
    "os.chmod": _f(_wrap_filename, write=True),
    "os.chroot": _f(_wrap_filename, write=False),
    "os.link": _f(_wrap_two_filenames),
    "os.listdir": _f(_wrap_os_listdir),
    "os.mkdir": _f(_wrap_filename, write=False),
    # ALLOW "os.makedirs" (indirect calls)
    # DENY os.mkfifo
    # DENY os.mknod
    "os.readlink": _f(_wrap_os_readlink),
    "os.remove": _f(_wrap_filename, write=True),
    # ALLOW os.removedirs (indirect calls)
    "os.rename": _f(_wrap_two_filenames, in_write=True, out_write=True),
    # ALLOW os.renames (indirect calls)
    "os.replace": _f(_wrap_two_filenames, in_write=True, out_write=True),
    "os.rmdir": _f(_wrap_os_rmdir),
    "os.scandir": _f(_wrap_os_scandir),
    "os.stat": _f(_wrap_os_stat, write=False),
    # ALLOW os.statvfs = _wrap_filename(os.statvfs)
    "os.lstat": _f(_wrap_filename, write=False, learn=False),
    # ALLOW os.stat_float_times
    "os.symlink": _f(_wrap_os_symlink),
    "os.truncate": _f(_wrap_filename, write=True),
    "os.unlink": _f(_wrap_os_unlink),
    "os.utime": _f(_wrap_filename, write=True, learn=False),
    # ALLOW os.fwalk (Indirect calls)
    # ALLOW os.walk (Indirect calls)
    # Posix
    "os.listxattr": _f(_wrap_filename, write=False),
    "os.removexattr": _f(_wrap_filename, write=True),
    "os.setxattr": _f(_wrap_filename, write=True),
    "os.getxattr": _f(_wrap_filename, write=False),
    # DENY os.execv
    # DENY os.execve
    # DENY os.execl
    # DENY os.execle
    # DENY os.execlp
    # DENY os.execlpe
    # DENY os.execvp
    # DENY os.execvpe
    # DENY os.spawnv
    # DENY os.spawnve
    # DENY os.spawnvp
    # DENY os.spawnvpe
    # DENY os.spawnl
    # DENY os.spawnle
    # DENY os.spawnlp
    # DENY os.spawnlpe
    # DENY os.popen
    # ALLOW os.getenv
    # ALLOW os.supports_bytes_environ
    # ALLOW os.environb
    # ALLOW os.getenvb
    # DENY os.fork
    # DENY os.forkpty
    # DENY os.kill
    # DENY os.killpg
    # DENY os.nice
    # DENY os.posix_spawn
    # DENY os.posix_spawnp
    # DENY os.putenv
    # DENY os.unsetenv
    # DENY os.system
    # %% high level access
    "io.open": _f(_wrap_io_open),
    "io.open_code": _f(_wrap_filename, write=False),
    # FIXME "io.FileIO": _f(_wrap_io_FileIO),
    # %%
    # ALLOW os.path.abspath
    # ALLOW os.path.basename
    # ALLOW os.path.dirname
    # "os.path.exists": _f(_wrap_os_path_exists, write=False),
    # "os.path.lexists": _f(_wrap_filename, write=False),
    # ALLOW os.path.expanduser
    # ALLOW os.path.expandvars
    # "os.path.getatime": _f(_wrap_filename, write=False),
    # "os.path.getmtime": _f(_wrap_filename, write=False),
    # "os.path.getctime": _f(_wrap_filename, write=False),
    # "os.path.getsize": _f(_wrap_filename, write=False),
    # ALLOW os.path.isabs
    # "os.path.isfile": _f(_wrap_os_path_is, write=False),
    # "os.path.isdir": _f(_wrap_os_path_is, write=False),
    # "os.path.islink": _f(_wrap_os_path_is, write=False),
    # ALLOW os.path.ismount
    # ALLOW os.path.join
    # ALLOW os.path.normcase
    # ALLOW os.path.normpath
    # "os.path.realpath": _f(_wrap_filename, write=False, learn=False),  # FIXME
    # ALLOW os.path.relpath
    # ALLOW os.path.samefile
    # ALLOW os.path.expanduser
    # ALLOW os.path.walk (obsolette)
    # pathlib
    # ALLOW pathlib.Path.stat
    # ALLOW pathlib.Path.lstat
    # ALLOW pathlib.Path.exists
    # ALLOW pathlib.Path.is_dir
    # ALLOW pathlib.Path.is_file
    # ALLOW pathlib.Path.is_mount
    # ALLOW pathlib.Path.is_symlink
    # ALLOW pathlib.Path.is_junction
    # ALLOW pathlib.Path.is_block_device
    # ALLOW pathlib.Path.is_char_device
    # ALLOW pathlib.Path.is_fifo
    # ALLOW pathlib.Path.is_socket
    # ALLOW pathlib.Path.samefile
    # ALLOW pathlib.Path.open
    # ALLOW pathlib.Path.read_bytes
    # ALLOW pathlib.Path.read_text
    # ALLOW pathlib.Path.write_bytes
    # ALLOW pathlib.Path.write_text
    # ALLOW pathlib.Path.iterdir
    "pathlib.Path.glob": _f(_wrap_pathlib_Path_glob),
    # ALLOW pathlib.Path.rglob
    # ALLOW pathlib.Path.walk
    # ALLOW pathlib.Path.relative_to
    # ALLOW pathlib.Path.is_relative_to
    # ALLOW pathlib.Path.is_absolute
    # ALLOW pathlib.Path.is_reserved
    # pathlib.Path.match
    # gzip
    # ALLOW gzip.open = _wrap_filename(gzip.open)
    # fileinput
    # ALLOW fileinput.input = _wrap_filename(fileinput.input)
    # shutil
    # ALLOW shutil.chown
    # ALLOW shutil.copy
    # ALLOW shutil.copy2
    # ALLOW shutil.copyfile
    # ALLOW shutil.copyfileobj
    # ALLOW shutil.copymode
    # ALLOW shutil.copystat
    # ALLOW shutil.copytree
    # ALLOW shutil.disk_usage
    # ALLOW shutil.make_archive
    # ALLOW shutil.move
    # "shutil.rmtree": _f(_wrap_filename, write=True),
    # ALLOW shutil.which
    # "tempfile._os": _f(_wrap__os),  # TODO: check python version
    # "pathlib._local.io": _f(_wrap__io),  # TODO: check python version
    # "pathlib._local.os": _f(_wrap__os),
    # "shutil.os": _f(_wrap__os),
    # builtins
    "builtins.open": _f(_wrap_buitins_open),
}


def patch_rules(learn: bool) -> dict[str, Callable]:
    """Provide file system patching rules for guard activation.

    Returns:
        Dictionary of file system module patches.
    """
    rules: dict[str, Callable] = dict(_default_rules)
    if sys.platform != "win32" and sys.platform != "linux":
        rules |= {
            "os.chflags": _f(_wrap_filename, write=True),
            "os.lchflags": _f(_wrap_filename, write=True),
            "os.lchmod": _f(_wrap_filename, write=True),
        }
    if sys.platform != "win32":
        rules |= {
            "os.chown": _f(_wrap_filename, write=True),
            "os.lchown": _f(_wrap_filename, write=True),
        }
    return rules


# %%
def activate_guard(rules: FileRules) -> None:
    """Activate file system guard with specified rules.

    Args:
        rules: File system access rules to enforce.
    """
    """
    Initializes the file access filter with the given rule list.
    Overrides built-in open and os.listdir functions.
    """
    global _rules
    assert rules is not None
    if _rules:
        logger.debug("Guard_files was already activated.")
    _rules = rules


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_files() -> None:
        global _rules
        _rules = (
            BindRule(
                source="/", dest="/", write=True, config=ConfigLine("pytest", Path(), 0)
            ),
        )
