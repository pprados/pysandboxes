import fnmatch
import functools
import inspect
import io
import logging
import os
import sys
from collections import OrderedDict
from io import FileIO
from os import scandir as _scandir
from pathlib import Path as _Path, Path
from types import TracebackType, ModuleType
from typing import Iterator, Dict, cast, Set, NoReturn
from typing import List, Callable, Optional, Union
from typing import NamedTuple, Any, Type, Tuple

from .config import OPTIMIZE
from .exceptions import RulePermissionError, RuleFileNotFoundError
from .guard_envs import LearnEnviron
from .learning import is_learning_mode, add_learning_rule
from .main_logger import format_ruleref, ErrorMsg
from .types import ConfigLines, ConfigLine

if io or os:
    pass

_Path_glob = _Path.glob
_Path_rglob = _Path.rglob

logger = logging.getLogger(__name__)

_white_list = [
    '<frozen posixpath>',
    '<frozen genericpath>',
]


# Internal representation of a rule
class BindRule(NamedTuple):
    source: str
    dest: Optional[str]
    write: bool
    config: ConfigLine


class IgnoreRule(NamedTuple):
    source: str
    config: ConfigLine


FilesRule = Union[BindRule, IgnoreRule]

FileRules = Tuple[FilesRule, ...]


class LearnFileRule(NamedTuple):
    path: Path
    write: bool


class _DirEntry:
    def __init__(self,
                 target: Any,
                 path: str) -> None:
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


def parse_rules(config: ConfigLines,
                errors: List[ErrorMsg],
                ) -> Tuple[FileRules, ConfigLines]:
    """
    Parses rule strings into internal ParserRule objects.
    Supports --bind=src,dest and --ignore=glob_pattern.
    """
    rules_ignore: List[FilesRule] = []
    rules_bind: List[FilesRule] = []
    ignore_rules: ConfigLines = []
    for rule in config:
        if rule.rule.startswith("bind=") or rule.rule.startswith("ro-bind="):
            value = rule.rule.split('=', 1)[1]
            try:
                src, dest = value.split(",", 1)
                if not src and not dest:
                    continue  # Ignore empty bind
                if src and dest:
                    src = _Path(src).expanduser()
                    dest = _Path(dest).expanduser()
                    if not src.is_dir() or not dest.is_dir():
                        errors.append(
                            (
                                f"{format_ruleref(rule)}: "
                                f"In {rule.rule!r}, "
                                f"source and destination must exists and be directories.",
                                rule.path,
                                rule.ln
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
                                        rule.ln
                                    )
                                )
                            else:
                                # Detect duplicate bind rule
                                break
                    else:
                        # Only one last "/"
                        src_str = str(Path(src)) + "/" if src != "/" else "/"
                        dest_str = str(Path(dest)) + "/" if dest != "/" else "/"
                        rules_bind.append(BindRule(source=src_str,
                                                   dest=dest_str,
                                                   write=rule.rule.startswith(
                                                       "bind="),
                                                   config=rule,
                                                   ))
                else:
                    errors.append(
                        (
                            f"{format_ruleref(rule)}: "
                            f"In {rule.rule!r}, "
                            f" source and destination must be set",
                            rule.path,
                            rule.ln
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
                        rule.ln
                    )
                )
                continue
        elif rule.rule.startswith("ignore="):
            pattern = rule.rule[len("ignore="):]
            rules_ignore.append(IgnoreRule(pattern, rule))
        else:
            ignore_rules.append(rule)
    rules_bind = sorted(rules_bind, key=lambda r: len(r.dest), reverse=True)

    return tuple(rules_ignore + rules_bind), ignore_rules


def _check_is_in_rules(path: Path):
    global _rules
    spath = str(path) + '/'
    for rule in _rules:
        if isinstance(rule, BindRule):
            if spath == rule.source:
                return True
    return False


_special_env = OrderedDict(
    sorted(
        (
            (k, LearnEnviron()._get(k)) for k in
            [
                "PWD",
                "HOME",
                "TMP", "TEMP",
            ]
            if k in LearnEnviron()
        ),
        key=lambda x: len(x[1]),
        reverse=True
    )
)

_special_home = OrderedDict(
    sorted(
        (
            (k, LearnEnviron()._get(k)) for k in
            [
                "PYENV_ROOT", "VIRTUAL_ENV", "CONDA_HOME",
                "HF_HOME", "HF_DATASETS_CACHE", "HF_MODULES_CACHE", "HF_HUB_CACHE",
                "TRANSFORMERS_CACHE"","
                "TORCH_HOME",
                "KERAS_HOME",
                "TFHUB_CACHE_DIR",
                "MXNET_HOME",
                "NLTK_DATA",
                "SPACY_DATA",
            ]
            if k in LearnEnviron()
        ),
        key=lambda x: len(x[1]),
        reverse=True)
)


def generate_rules(
        learn: Set[Any],
) -> List[str]:
    # Select only parent
    global _special_env, _special_home
    parent_level: Dict[Path, bool] = {}
    for learn_rule in filter(lambda x: isinstance(x, LearnFileRule), learn):
        parent = learn_rule.path.absolute()
        if not parent.is_dir():
            parent = parent.parent
        if not parent_level.get(parent, False) and learn_rule.write:
            parent_level[parent] = True
        else:
            parent_level[parent] = False

    result: Set[str] = set()
    home = Path.home().absolute()

    allready_added: List[LearnFileRule] = []
    for path in sorted(parent_level.keys()):
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
                        value = f"${{{key}}}" + x
                    break
        if not value:
            value = str(path)
        if value:
            result.add(
                "" +
                f'{"" if write else "ro-"}bind={value},{value}'
            )
        if path != home:
            allready_added.append(LearnFileRule(path, write))
    return sorted(list(result), reverse=True)


# Helper to resolve symlinks and apply rules
def _apply_src_to_dest_rules(path: str, accept_src: bool = False) -> Tuple[
    Optional[str],
    Optional[FilesRule]
]:
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
            if real_path.startswith(rule.source) or real_path == rule.source[:-1]:
                if not accept_src and real_path == rule.source[:-1]:
                    return None, rule
                relative = os.path.relpath(real_path, rule.source)
                if relative != ".":
                    new_path = os.path.join(rule.dest, relative)
                else:
                    new_path = rule.dest
                return new_path, None
        elif isinstance(rule, IgnoreRule):
            if fnmatch.fnmatch(original_path, rule.source) or fnmatch.fnmatch(
                    real_path, rule.source):
                return None, rule
        else:
            assert "Invalide rules"
    return path, None


# Helper to resolve symlinks and apply rules
def _apply_dest_to_src_rules(path: Union[str, os.PathLike, _DirEntry],
                             *,
                             write: bool,
                             accept_source: bool = False,
                             ) -> Tuple[Optional[str], Optional[FilesRule]]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    if not path:
        return None
    if isinstance(path, _DirEntry):
        path = path.path
    fake_path = _os_path_abspath(path)
    # if str(path).endswith("/"):
    #     fake_path = fake_path + "/"
    original_path = path

    for rule in _rules:
        if isinstance(rule, BindRule):
            if rule.source != rule.dest and fake_path.startswith(
                    rule.source[:-1]) and not accept_source:
                return None, rule
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
                            f"Rule {rule.config.rule!r} from {format_ruleref(rule.config)}"
                        )
                relative = os.path.relpath(fake_path_dir, rule.dest)
                if relative == ".":
                    relative = ""
                new_path = os.path.join(rule.source, relative)
                return new_path, None
        elif isinstance(rule, IgnoreRule):
            if rule.source[0] == "/":
                if fnmatch.fnmatch(original_path, rule.source) or fnmatch.fnmatch(
                        fake_path, rule.source):
                    return None, rule
            else:
                if (fnmatch.fnmatch(Path(original_path).name, rule.source) or
                        fnmatch.fnmatch(
                            Path(fake_path).name, rule.source)):
                    return None, rule
        else:
            assert False, "Invalide guard_files rules"
    return None, None


def _special_caller():
    frame = sys._getframe(2)
    filename = None
    if inspect.isframe(frame):
        code = frame.f_code
        filename = code.co_filename
    for wl in _white_list:
        if filename.endswith(wl):
            return True
    return False


def _raise_ignore(file: Union[str, bytes, os.PathLike, int],
                  rule: FilesRule) -> NoReturn:
    assert rule is not None

    raise RuleFileNotFoundError(
        f"Access to {file!r} is ignored by "
        f"rule {rule.config.rule!r} from {format_ruleref(rule.config)}"
    )


def _raise_access(file: Union[str, bytes, os.PathLike, int]) -> NoReturn:
    f = Path(file)
    if not f.is_dir():
        f = f.parent
    try:
        sf = str(f.absolute().relative_to(Path().absolute()))
        if sf != ".":
            sf = "./" + sf
    except ValueError:
        sf = str(f)
    raise RuleFileNotFoundError(f"Access to {sf}/' must be accepted by a rule.")


# %% Generic wrapper
def _wrap_empty(func: Callable) -> Callable:
    return func


def _wrap_reload_module(func: Callable, *, name: str) -> ModuleType:
    # Use _f(_wrap_reload_module, name="io") to refresh a module in another module
    import sys
    return sys.modules[name]


def _wrap_buitins_open(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(
            file, mode='r',
            *args, **kwargs
    ):
        if _special_caller():
            return func(file, *args, **kwargs)
        need_to_write = mode is not None and (
                "w" in mode or "a" in mode or "x" in mode or "+" in mode)
        remapped, rule = _apply_dest_to_src_rules(file, write=need_to_write)
        if rule:
            _raise_ignore(file, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file), write=need_to_write))
                remapped = file
            else:
                _raise_access(file)
        return func(remapped, mode=mode, *args, **kwargs)

    return wrapper


def _wrap_filename(func: Callable, *, write: bool) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike, int],
                *args, **kwargs
                ):
        # Detect call from posixpath
        if _special_caller():
            return func(file, *args, **kwargs)
        if isinstance(file, int):
            return func(file, *args, **kwargs)
        if isinstance(file, _DirEntry):
            file = file.path
        remapped, rule = _apply_dest_to_src_rules(file, write=write)
        if rule:
            _raise_ignore(file, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file), write))
                remapped = file
            else:
                _raise_access(file)
        return func(remapped, *args, **kwargs)

    return wrapper


def _wrap_two_filenames(func: Callable, *,
                        in_write: bool = False,
                        out_write: bool = True) -> Callable:
    @functools.wraps(func)
    def wrapper(src: Union[str, bytes, os.PathLike],
                dest: Union[str, bytes, os.PathLike],
                *args, **kwargs):
        # Detect call from posixpath
        if _special_caller():
            return func(src, dest, *args, **kwargs)
        if isinstance(src, _DirEntry):
            src = src.path
        if isinstance(dest, _DirEntry):
            dest = dest.path
        remapped_src, rule1 = _apply_dest_to_src_rules(src, write=in_write)
        if rule1:
            _raise_ignore(src, rule1)
        remapped_dest, rule2 = _apply_dest_to_src_rules(dest,
                                                        write=out_write)
        if rule2:
            _raise_ignore(dest, rule2)
        if remapped_src is None:
            _raise_ignore(src, rule1)
        return func(str(remapped_src), str(remapped_dest), *args, **kwargs)

    return wrapper


def _wrap_os_path_samefile(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(src: Union[str, bytes, os.PathLike, _DirEntry],
                dest: Union[str, bytes, os.PathLike],
                *args, **kwargs):
        # Detect call from posixpath
        if _special_caller():
            return func(src, dest, *args, **kwargs)
        remapped_src, rule1 = _apply_dest_to_src_rules(src, write=False)
        if rule1:
            _raise_ignore(src, rule1)
        remapped_dest = None
        if remapped_src is not None:
            remapped_dest, rule2 = _apply_dest_to_src_rules(dest,
                                                            write=False)
            if rule2:
                _raise_ignore(dest, rule2)
        if remapped_dest is None:
            remapped_dest = dest
        return func(str(remapped_src), str(remapped_dest), *args, **kwargs)

    return wrapper


def _wrap_dir(func: Callable, *, write: bool) -> Callable:
    @functools.wraps(func)
    def wrapper(dir: Union[str, bytes, os.PathLike, int], *args, **kwargs):
        # Detect call from posixpath
        new_dir = dir
        if _special_caller():
            return func(new_dir, *args, **kwargs)
        if isinstance(dir, int):
            return func(dir, *args, **kwargs)
        new_dir = os.fspath(dir)
        if not new_dir.endswith("/"):
            new_dir = new_dir + "/"
        remapped, rule = _apply_dest_to_src_rules(new_dir, write=write)
        if rule:
            _raise_ignore(dir, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(dir), write))
                remapped = dir
            else:
                _raise_access(dir)
        return func(remapped, *args, **kwargs)

    return wrapper


def _wrap_os_path_exists(func: Callable, *, write: bool) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike, int], *args, **kwargs):
        # Detect call from posixpath
        if _special_caller():
            return func(file, *args, **kwargs)
        if isinstance(file, int):
            return func(file, *args, **kwargs)
        if isinstance(file, _DirEntry):
            file = file.path
        remapped, rule = _apply_dest_to_src_rules(file, write=write)
        if rule:
            return False
        if remapped is None:
            if is_learning_mode():
                # exist is not learn.
                # add_learning_rule(LearnFileRule(Path(file), False))
                remapped = file
            else:
                return False
        return func(remapped, *args, **kwargs)

    return wrapper


def _wrap_os_path_is(func: Callable, *, write: bool) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike, int], *args, **kwargs):
        # Detect call from posixpath
        if _special_caller():
            return func(file, *args, **kwargs)
        if isinstance(file, int):
            return func(file, *args, **kwargs)
        if isinstance(file, _DirEntry):
            file = file.path
        remapped, rule = _apply_dest_to_src_rules(file, write=write)
        if rule:
            return False
        if remapped is None:
            return False
        return func(remapped, *args, **kwargs)

    return wrapper


# %% os wrapper
def _wrap_os_open(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike, int],
                flags: int,
                *args, **kwargs):
        # Detect call from posixpath
        if _special_caller():
            return func(file, flags, *args, **kwargs)
        if isinstance(file, int):
            return func(file, flags, *args, **kwargs)
        if isinstance(file, _DirEntry):
            file = file.path
        if isinstance(flags, int):
            need_to_write = bool((flags & os.O_WRONLY) or (flags & os.O_RDWR) or (
                    flags & os.O_APPEND))
            remapped, rule = _apply_dest_to_src_rules(file,
                                                      write=need_to_write)
            if remapped is None:
                if is_learning_mode():
                    add_learning_rule(LearnFileRule(Path(file), False))
                    remapped = file
                else:
                    _raise_access(file)
        return func(remapped, flags, *args, **kwargs)

    return wrapper


def _wrap_os_getcwd(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Detect call from posixpath
        dir = func(*args, **kwargs)
        new_dir = os.fspath(dir)
        if not new_dir.endswith("/"):
            new_dir = new_dir + "/"

        remapped, rule = _apply_src_to_dest_rules(new_dir, accept_src=True)
        # remapped, rule = _apply_dest_to_src_rules(new_dir,write=False, accept_source=True)
        if remapped.endswith(os.path.sep + "."):
            remapped = remapped[:-2]
        if remapped.endswith(os.path.sep):
            remapped = remapped[:-1]
        return str(remapped)

    return wrapper


def _wrap_os_getcwdb(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Detect call from posixpath
        dir = func(*args, **kwargs)
        new_dir = os.fspath(dir.decode())
        if not new_dir.endswith("/"):
            new_dir = new_dir + "/"

        remapped, rule = _apply_src_to_dest_rules(new_dir, accept_src=True)
        # remapped, rule = _apply_dest_to_src_rules(new_dir,write=False, accept_source=True)
        if remapped.endswith(os.path.sep + "."):
            remapped = remapped[:-2]
        if remapped.endswith(os.path.sep):
            remapped = remapped[:-1]
        if remapped == new_dir:
            return dir
        return str(remapped).encode(sys.getfilesystemencoding())

    return wrapper


def _wrap_os_listdir(func: Callable[..., List[str]]) -> Callable[..., List[str]]:
    @functools.wraps(func)
    def wrapper(path: Union[str, bytes, os.PathLike] = '.') -> list[str]:
        if new_path_and_rule := _apply_dest_to_src_rules(path, write=False):
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
            filtered: List[str] = []
            for entry in entries:
                full_path = os.path.join(path, entry)
                remapped, _ = _apply_dest_to_src_rules(full_path, write=False,
                                                       accept_source=False)
                if remapped is not None:
                    filtered.append(entry)
            return filtered
        else:
            return []

    return wrapper


def _wrap_os_readlink(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike], *args, **kwargs):
        remapped_first, rule = _apply_dest_to_src_rules(file, write=False)
        if rule:
            _raise_ignore(file, rule)
        if not remapped_first:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file), False))
                remapped_first = file
            else:
                return None, None
        remapped = func(remapped_first, *args, **kwargs)
        if not remapped.startswith(os.path.sep):
            remapped = os.path.dirname(remapped_first) + os.path.sep + remapped
        remapped, rule = _apply_src_to_dest_rules(remapped)
        if rule:
            _raise_ignore(file, rule)
        if not remapped:
            _raise_ignore(file, rule)
        return remapped

    return wrapper


class _ScanDirContextManager:
    """
    A context manager that wraps os.scandir and implements the context manager protocol.
    """

    __slot__ = ("directory", "real_directory", "scanner")

    def close(self):
        if self.scanner:
            self.scanner.shutdown()

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
        self.scanner = None

    def __enter__(self) -> '_ScanDirContextManager':
        """
        Enter the context manager, opening the scandir iterator.
        """
        self.scanner = _scandir(self.real_directory)
        self.scanner.__enter__()
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]],
                 exc_val: Optional[BaseException],
                 exc_tb: Optional[TracebackType]) -> bool:
        """
        Exit the context manager, closing the scandir iterator.
        """
        if self.scanner is not None:
            return self.scanner.__exit__(
                exc_type, exc_val, exc_tb
            )
        return False  # Don't suppress exceptions

    def __iter__(self) -> 'ScanDirContextManager':
        """
        Make the context manager iterable.
        """
        if is_learning_mode() and OPTIMIZE:
            return self.scanner.__iter__()
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
                    entry = next(self.scanner)
                    dest_path, rule = _apply_src_to_dest_rules(entry.path,
                                                               accept_src=False)
                    if rule:
                        pass  # Ignore
                    elif dest_path is not None:
                        _entry = _DirEntry(entry, dest_path)
                        return cast(os.DirEntry,_entry)
            except StopIteration:
                raise


def _wrap_os_scandir(func: Callable) -> Callable:
    """
    Wrap os.scandir to handle exceptions and return an iterator or None.
    """

    @functools.wraps(func)
    def wrapper(path: Union[str, bytes, os.PathLike, int] = '.') -> Iterator:
        if isinstance(path, int):
            return func(path)
        return _ScanDirContextManager(path)

    return wrapper


# %% os.path wrapper
def _wrap_os_path_realpath(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike], *args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename = None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(*args, **kwargs)
        remapped, rule = _apply_dest_to_src_rules(file, write=False)
        if rule:
            _raise_ignore(file, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file), False))
                remapped = file
            else:
                _raise_access(file)
        file = func(remapped, *args, **kwargs)
        remapped, rule = _apply_src_to_dest_rules(os.fspath(file))
        if remapped is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file), False))
                remapped = os.fspath(file)
            else:
                _raise_access(file)
        return remapped

    return wrapper


# %% io wrapper
def _wrap_io_open(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike, int],
                mode: str = "r",
                *args, **kwargs):
        # Detect call from posixpath
        if _special_caller():
            return func(file, mode, *args, **kwargs)
        if isinstance(file, int):
            return func(file, mode, *args, **kwargs)
        if isinstance(file, _DirEntry):
            file = file.path
        need_to_write = mode is not None and (
                "w" in mode or "a" in mode or "x" in mode or "+" in mode)
        remapped, rule = _apply_dest_to_src_rules(file, write=need_to_write)
        if rule:
            _raise_ignore(file, rule)
        if remapped is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file).absolute(), need_to_write))
                remapped = file
            else:
                _raise_access(file)
        return func(remapped, mode, *args, **kwargs)

    return wrapper


# %% pathlib wrapper
def _wrap_pathlib(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike], *args, **kwargs):
        remapped, rule = _apply_dest_to_src_rules(file, write=False)
        if rule:
            _raise_ignore(file, rule)
        if remapped is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(file), False))
            else:
                _raise_access(file)
        return func(Path(remapped), *args, **kwargs)

    return wrapper


class Guard_FileIO(FileIO):
    @staticmethod  # known case of __new__
    def __new__(cls,
                name,
                mode: str = "r",
                closefd=True,
                opener=None,
                *args, **kwargs):  # real signature unknown
        """ Create and return a new object.  See help(type) for accurate signature. """
        need_to_write = mode is not None and (
                "w" in mode or "a" in mode or "x" in mode or "+" in mode)
        remapped, rule = _apply_dest_to_src_rules(name, write=need_to_write,
                                                  accept_source=False)
        if rule:
            _raise_ignore(remapped, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(name), need_to_write))
                remapped = name
            else:
                _raise_access(remapped)
        return io.FileIO(str(remapped), mode=mode, closefd=closefd, opener=opener,
                         *args, **kwargs)


# Wrapper for factory to wrapper ;-)
def _f(func, *args, **kwargs):
    def wrapper():
        def wrapper2(original):
            return func(original, *args, **kwargs)

        return wrapper2

    return wrapper()


# _f(_wrap_filename,write=True)(toto)("abc")
# def _wrap_filename(*args,**kwargs):
#     return _f(wrap_filename,*args,**kwargs)

_default_rules = rules = {
    "os.chdir": _f(_wrap_dir, write=False),
    # ALLOW os.fchdir
    "os.getcwd": _f(_wrap_os_getcwd),
    "os.getcwdb": _f(_wrap_os_getcwdb),
    # ALLOW os.fdopen
    "os.open": _f(_wrap_os_open),
    "os.access": _f(_wrap_filename, write=False),
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
    "os.rmdir": _f(_wrap_filename, write=True),
    "os.scandir": _f(_wrap_os_scandir),
    "os.stat": _f(_wrap_filename, write=False),
    # ALLOW os.statvfs = _wrap_filename(os.statvfs)
    "os.lstat": _f(_wrap_filename, write=False),
    # ALLOW os.stat_float_times
    "os.symlink": _f(_wrap_two_filenames, in_write=False, out_write=True),
    "os.truncate": _f(_wrap_filename, write=True),
    "os.unlink": _f(_wrap_filename, write=True),
    "os.utime": _f(_wrap_filename, write=True),
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
    "io.FileIO": lambda x: Guard_FileIO,

    # %%
    # ALLOW os.path.abspath
    # ALLOW os.path.basename
    # ALLOW os.path.dirname
    "os.path.exists": _f(_wrap_os_path_exists, write=False),
    "os.path.lexists": _f(_wrap_filename, write=False),
    # ALLOW os.path.expanduser
    # ALLOW os.path.expandvars
    "os.path.getatime": _f(_wrap_filename, write=False),
    "os.path.getmtime": _f(_wrap_filename, write=False),
    "os.path.getctime": _f(_wrap_filename, write=False),
    "os.path.getsize": _f(_wrap_filename, write=False),
    # ALLOW os.path.isabs
    "os.path.isfile": _f(_wrap_os_path_is, write=False),
    "os.path.isdir": _f(_wrap_os_path_is, write=False),
    "os.path.islink": _f(_wrap_os_path_is, write=False),
    # ALLOW os.path.ismount
    # ALLOW os.path.join
    # ALLOW os.path.normcase
    # ALLOW os.path.normpath
    "os.path.realpath": _f(_wrap_os_path_realpath),
    # ALLOW os.path.relpath
    "os.path.samefile": _f(_wrap_os_path_samefile),
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
    # ALLOW pathlib.Path.glob
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
    # ALLOW shutil.rmtree
    # ALLOW shutil.which

    # builtins
    "builtins.open": _f(_wrap_buitins_open),

}


def patch_rules() -> Dict[str, Callable]:
    rules = dict(_default_rules)
    if sys.platform != "win32" and sys.platform != "linux":
        rules = {**rules, **{
            "os.chflags": _f(_wrap_filename, write=True),
            "os.lchflags": _f(_wrap_filename, write=True),
            "os.lchmod": _f(_wrap_filename, write=True),
        }}
    if sys.platform != "win32":
        rules = {**rules, **{
            "os.chown": _f(_wrap_filename, write=True),
            "os.lchown": _f(_wrap_filename, write=True),
        }}
    return rules


# %%
if "PYTEST_RUN_CONFIG" in os.environ:
    def _deactivate_guard_files():
        global _rules
        _rules = ()


def activate_guard(
        rules: FileRules
) -> None:
    """
    Initializes the file access filter with the given rule list.
    Overrides built-in open and os.listdir functions.
    """
    if not rules:
        return
    global _rules
    if _rules:
        logger.debug("Guard_files was already activated.")
    _rules = rules
