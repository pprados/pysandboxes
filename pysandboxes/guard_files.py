# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""File system access guard for PySandboxes.

This module implements comprehensive file system sandboxing by intercepting and
controlling access to files and directories. It provides a whitelist-based security
model with support for ignore patterns, path exposure (host↔sandbox), and access logging.

The guard patches standard library functions like open(), Path operations, and
directory scanning to enforce security rules defined in the configuration.
"""

import contextvars
import fnmatch
import importlib
import io
import logging
import ntpath
import os
import re
import sys
from collections import OrderedDict
from errno import ENOENT
from os import scandir as _scandir
from pathlib import Path as Path
from types import ModuleType, TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterator,
    NamedTuple,
    NoReturn,
    Type,
    TypeAlias,
    cast,
)

if sys.platform == "darwin":
    import fcntl

from .config import OPTIMIZE
from .e import RuleFileNotFoundError, RulePermissionError
from .guard_envs import LearnEnviron
from .guard_wraps import guard_wraps
from .learning import add_learning_rule, is_learning_mode
from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLine, ConfigLines
from .tools import follow_links_executable
from .tools import patch_factory as _f

if io or os:
    pass

if TYPE_CHECKING:
    import pathlib

_Path_glob = Path.glob
_Path_rglob = Path.rglob

logger = logging.getLogger(__name__)

StrOrBytesPath: TypeAlias = str | bytes | os.PathLike[str] | os.PathLike[bytes]  # stable

_check_alias: contextvars.ContextVar[bool] = contextvars.ContextVar("_check_alias", default=True)


# Internal representation of a rule
class FSExposeRule(NamedTuple):
    """Expose a host path with read-only or read-write access (same path in the sandbox).

    Attributes:
        path: Absolute or normalized path (directory with trailing ``/``, except ``/``).
        write: Whether read-write access is allowed (False = read-only).
        config: Configuration line where rule was defined.
    """

    path: str
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


FilesRule = FSExposeRule | IgnoreRule

FilesRules = tuple[FilesRule, ...]


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
        super().__init__()
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

    def __fspath__(self) -> str:
        # Implicit dunder lookups bypass ``__getattr__``, so ``os.fspath()`` cannot reach the
        # delegated attribute. Like a real ``os.DirEntry``, it must match ``.path``.
        return self._path

    def __str__(self) -> str:
        return str(self._target.path)


# Internal state for the file filter
_rules: FilesRules = cast(FilesRules, ())

_os_path_realpath = os.path.realpath
_os_path_abspath = os.path.abspath
_os_readlink = os.readlink

# Set while the guard canonicalizes a path for itself. ``os.path.realpath``
# calls ``os.lstat``/``os.readlink``, which are patched, so canonicalizing
# inside the check would recurse forever.
_canonicalizing: contextvars.ContextVar[bool] = contextvars.ContextVar("_canonicalizing", default=False)


def _dir_path(path: str) -> str:
    """Return ``path`` ending with the native separator, the form directory rules are stored in.

    A literal '/' would never prefix a Windows rule such as 'D:\\a\\'.
    """
    return path if path.endswith(("/", os.sep)) else path + os.sep


def _safe_realpath(path: str) -> str:
    """Resolve symlinks in ``path`` without re-entering the file guard."""
    token = _canonicalizing.set(True)
    try:
        return _os_path_realpath(path)
    finally:
        _canonicalizing.reset(token)


# System CA stores: Debian/Ubuntu (/etc/ssl, whose certs link to /usr/share/ca-certificates),
# Fedora/RHEL (/etc/pki, /usr/share/pki), Arch (/etc/ca-certificates).
_CA_STORES = (
    "/etc/ssl/",
    "/etc/pki/",
    "/etc/ca-certificates/",
    "/usr/share/ca-certificates/",
    "/usr/share/pki/",
)


def parse_rules(
    config: ConfigLines,
    errors: list[ErrorMsg],
) -> tuple[FilesRules, ConfigLines]:
    """Parse file system access rules from configuration.

    Supports expose-ro=path, expose-rw=path, and ignore=glob_pattern rules.

    Args:
        config: Configuration lines to parse.
        errors: List to collect parsing errors.

    Returns:
        Tuple of parsed file rules and remaining config lines.
    """
    """
    Parses rule strings into internal ParserRule objects.
    Supports expose-ro=path, expose-rw=path, and --ignore=glob_pattern.
    """
    rules_ignore: list[FilesRule] = []
    rules_expose: list[FSExposeRule] = []
    ignore_rules: ConfigLines = []
    for rule in config:
        if rule.rule.startswith("expose-ro=") or rule.rule.startswith("expose-rw="):
            value = rule.rule.split("=", 1)[1].strip()
            if "," in value:
                errors.append(
                    (
                        f"{format_ruleref(rule)}: " f"In {rule.rule!r}, " f"expected a single path (no comma).",
                        rule.path,
                        rule.ln,
                    )
                )
                continue
            if not value:
                errors.append(
                    (
                        f"{format_ruleref(rule)}: " f"In {rule.rule!r}, path must be set.",
                        rule.path,
                        rule.ln,
                    )
                )
                continue
            s_path = value
            try:
                resolved = Path(Path(s_path).expanduser()).resolve().absolute()
            except (OSError, ValueError):
                errors.append(
                    (
                        f"{format_ruleref(rule)}: " f"In {rule.rule!r}, path is invalid.",
                        rule.path,
                        rule.ln,
                    )
                )
                continue
            if not resolved.exists():
                cwd = Path.cwd()
                rel = str(resolved.relative_to(cwd)) if resolved.is_relative_to(cwd) else str(resolved)
                errors.append(
                    (
                        f"{format_ruleref(rule)}: " f"In {rule.rule!r}, path {rel!r} must exist.",
                        rule.path,
                        rule.ln,
                    )
                )
                continue
            if not resolved.is_dir():
                errors.append(
                    (
                        f"{format_ruleref(rule)}: " f"In {rule.rule!r}, path must be a directory.",
                        rule.path,
                        rule.ln,
                    )
                )
                continue
            is_write = rule.rule.startswith("expose-rw=")
            path_str = _dir_path(str(resolved))
            for expose_rule in rules_expose:
                if expose_rule.path == path_str:
                    if expose_rule.write != is_write:
                        errors.append(
                            (
                                f"{format_ruleref(rule)}: "
                                f"In {rule.rule!r}, "
                                f"invalidate another rule "
                                f"from {format_ruleref(expose_rule.config)!r}.",
                                rule.path,
                                rule.ln,
                            )
                        )
                    break
            else:
                rules_expose.append(
                    FSExposeRule(
                        path=path_str,
                        write=is_write,
                        config=rule,
                    )
                )
        elif rule.rule.startswith("ignore="):
            pattern = rule.rule[len("ignore=") :]
            rules_ignore.append(IgnoreRule(pattern, rule))
        else:
            ignore_rules.append(rule)

    # Add path for python
    list_bin = list(follow_links_executable(Path(sys.executable), set()))
    for p in list_bin:
        # The link and its target both need a rule. Resolving here collapses the two
        # names the chain walks through into one, and inside the sandbox the
        # interpreter reports the *link* name: a uv venv puts sysconfig's stdlib under
        # .../cpython-3.14-linux-x86_64-gnu, so a rule registered only for the resolved
        # .../cpython-3.14.5-... denies it, and `import colorsys` fails with "Access to
        # ... must be accepted by a rule" long before the import guard has its say.
        for rp in dict.fromkeys((Path(p), Path(p).resolve())):
            if rp.is_dir():
                p_str = _dir_path(str(rp))
            else:
                p_str = str(rp)
            rules_expose.append(
                FSExposeRule(
                    path=p_str,
                    write=False,
                    config=ConfigLine("<python>", Path(), 0),
                )
            )
    # OpenSSL reads the CA store from C: the Python guards never see it, the OS
    # providers do, and HTTPS then fails with "certificate verify failed". Where it
    # lives depends on the distribution, and exposing a missing path is an error.
    for store in _CA_STORES:
        if Path(store).is_dir():
            rules_expose.append(
                FSExposeRule(path=store, write=False, config=ConfigLine("<ca-certificates>", Path(), 0))
            )
    rules_expose = sorted(rules_expose, key=lambda r: len(r.path), reverse=True)
    return tuple(rules_ignore + cast(list[FilesRule], rules_expose)), ignore_rules


def _check_is_in_rules(path: Path) -> bool:
    """Check if path is covered by existing rules.

    Args:
        path: Path to check.

    Returns:
        True if path is covered by rules, False otherwise.
    """
    global _rules
    spath = str(path) + os.sep
    for rule in _rules:
        if isinstance(rule, FSExposeRule):
            if spath == rule.path:
                return True
    return False


_learn_env = LearnEnviron()

# tempfile.gettempdir() falls back to this when TMPDIR, TEMP and TMP are all unset.
_TMP_FALLBACK = "/tmp"

_special_env = OrderedDict(
    sorted(
        (
            (k, cast(str, v))
            for k in [
                "PWD",
                "HOME",
                # TMPDIR is the POSIX name and comes first; TMP and TEMP are Windows
                # conventions, kept for a profile learned there. None of the three is
                # set on a stock Linux shell, which is what _TMP_FALLBACK answers for.
                "TMPDIR",
                "TMP",
                "TEMP",
            ]
            if (v := _learn_env.get(k)) is not None
        ),
        key=lambda x: len(x[1]),
        reverse=True,
    )
)

_special_home = OrderedDict(
    sorted(
        (
            (k, cast(str, v))
            for k in [
                "PYENV_ROOT",
                "VIRTUAL_ENV",
                "CONDA_HOME",
                "HF_HOME",
                "HF_DATASETS_CACHE",
                "HF_MODULES_CACHE",
                "HF_HUB_CACHE",
                "TRANSFORMERS_CACHE",
                "TORCH_HOME",
                "KERAS_HOME",
                "TFHUB_CACHE_DIR",
                "MXNET_HOME",
                "NLTK_DATA",
                "SPACY_DATA",
            ]
            if (v := _learn_env.get(k)) is not None
        ),
        key=lambda x: len(x[1]),
        reverse=True,
    )
)


def generate_rules(
    learn: set[Any],
) -> list[str]:
    """Generate file system rules from learning data.

    Creates expose-ro/expose-rw and ignore rules based on observed file access
    during learning mode execution.

    Args:
        learn: Set of learned file access patterns.

    Returns:
        List of expose-ro=/expose-rw= and ignore= configuration rule strings.
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
        if path.exists() and (path.is_file() or path.is_dir()) and os.access(path, os.R_OK):
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
                            # POSIX separators: the fallback and ~ are POSIX, and a learned profile travels
                            x = "/" + path.relative_to(val).as_posix()
                            if x == "/.":
                                x = ""
                            if key == "PWD":
                                value = "." + x
                            elif key == "HOME":
                                value = "~" + x
                            else:
                                # Every remaining key names a temporary directory, and
                                # none of them is set on a stock Linux shell or a CI
                                # runner. A bare ${VAR} would expand to nothing there
                                # and make the whole file a syntax error, so the rule
                                # carries the one fallback that holds everywhere.
                                # Only these keys get a default: for a key naming a
                                # machine-specific path, a default would silently
                                # expose the learning machine's directory instead of
                                # failing where a human can see it.
                                value = f"${{{key}:-{_TMP_FALLBACK}}}" + x
                        break
            if not value:
                value = str(path)
            if value and value != "${HOME}":
                result.add(f'{"expose-rw" if write else "expose-ro"}={value}')
            if path != home:
                allready_added.append(LearnFileRule(path, write))
    return sorted(list(result))


def _without_ntfs_streams(path: str) -> str:
    """Drop the ``:stream`` suffix NTFS accepts on any component: ``d::$INDEX_ALLOCATION\\f`` opens ``d\\f``."""
    drive, rest = ntpath.splitdrive(path)
    return drive + "".join(part.split(":", 1)[0] for part in re.split(r"([\\/])", rest))


def _ignore_matches(name: str, pattern: str) -> bool:
    """Match an ``ignore=`` pattern against every spelling the file system resolves to the same file.

    fnmatch already folds case on Windows, not on macOS, whose APFS ignores it by default:
    on a case-sensitive volume this denies more, never less.
    """
    if sys.platform == "win32":
        name = _without_ntfs_streams(name)
    elif sys.platform == "darwin":
        name, pattern = name.casefold(), pattern.casefold()
    return fnmatch.fnmatch(name, pattern)


def _apply_ignore_rule(
    path: str | os.PathLike[str] | os.PathLike[bytes],
) -> tuple[str | None, FilesRule | None]:
    for rule in _rules:
        if isinstance(rule, IgnoreRule):
            assert rule.source is not None
            if _ignore_matches(Path(str(path)).name, rule.source):
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
    if _canonicalizing.get():
        # Called back by our own realpath through the patched os.readlink, which
        # checks the link target on the way out. Same reason as the symmetric
        # guard in _apply_dest_to_src_rules: the outer call decides on the fully
        # resolved path. Without this, an intermediate link pointing at an
        # ignored name aborted the canonicalization itself.
        return real_path, None
    # if path.endswith("/"):
    #     real_path = real_path + "/"
    original_path = path

    for rule in _rules:
        if isinstance(rule, FSExposeRule):
            assert rule.path is not None
            rp = rule.path
            if real_path.startswith(rp) or real_path == rp[:-1]:
                return real_path, None
        elif isinstance(rule, IgnoreRule):
            if _ignore_matches(original_path, rule.source) or _ignore_matches(real_path, rule.source):
                return None, rule
        else:
            assert False, f"Invalid guard_files rules {type(rule)=}"  # noqa: B011
    return path, None


# Helper to resolve symlinks and apply rules
def _apply_dest_to_src_rules(
    path: str | os.PathLike[str] | _DirEntry,
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
    if _canonicalizing.get():
        # Called back by our own realpath through the patched os.lstat /
        # os.readlink. Do not re-check here: the resolved path is checked
        # by the outer call that started the canonicalization.
        return _os_path_abspath(str(path)), None
    fake_path: str = _os_path_abspath(str(path))
    is_dir_form = str(path).endswith(("/", os.sep))
    if is_dir_form:
        fake_path = fake_path + os.sep
    # The decision is taken on the canonical path, so that a symlink cannot
    # authorize an access outside the exposed directories (the rules are
    # stored realpath-resolved, see parse_rules). The path *returned* stays
    # unresolved: it is the one handed to the real syscall, and resolving it
    # would change link semantics (os.path.islink, os.readlink, ...).
    canon_path: str = _safe_realpath(str(path))
    if is_dir_form:
        canon_path = canon_path + os.sep
    original_path = path

    for rule in _rules:
        if isinstance(rule, FSExposeRule):
            if rule.path is None:
                continue
            rp = rule.path
            if canon_path.startswith(rp) or canon_path == rp[:-1]:
                if not rule.write and write:
                    if is_learning_mode():
                        add_learning_rule(LearnFileRule(Path(str(path)), True))
                    else:
                        raise RulePermissionError(
                            f"Cannot write to {rp!r}. "
                            f"Rule {rule.config.rule!r} from "
                            f"{format_ruleref(rule.config)}"
                        )
                return fake_path, None
        elif isinstance(rule, IgnoreRule):
            assert rule.source is not None
            # The canonical path catches a link, a device prefix or a short name to the ignored file.
            spellings: tuple[str, ...] = (str(original_path), fake_path, canon_path)
            if not os.path.isabs(rule.source):
                spellings = tuple(Path(spelling).name for spelling in spellings)
            if any(_ignore_matches(spelling, rule.source) for spelling in spellings):
                return None, rule
        else:
            assert False, f"Invalid guard_files rules {type(rule)=}"  # noqa: B011
    return None, None


def _raise_ignore(file: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int, rule: FilesRule) -> NoReturn:
    assert rule is not None

    ex = RuleFileNotFoundError(
        f"Access to {file!r} is ignored by " f"rule {rule.config.rule!r} from {format_ruleref(rule.config)}"
    )
    ex.errno = ENOENT
    raise ex


def _raise_access(file: str) -> NoReturn:
    path = Path(file)
    try:
        f = str(path.absolute())
    except ValueError:
        f = str(path)
    ex = RuleFileNotFoundError(f"Access to {f!r} must be accepted by a rule.")
    ex.errno = ENOENT
    raise ex


def _dir_fd_path(path: str, dir_fd: int) -> str:
    """Return the path the kernel resolves ``path`` to, relative to the directory open as ``dir_fd``.

    An unresolvable descriptor denies the call: checking ``path`` against the current
    directory instead would let ``shutil.rmtree`` empty a read-only tree.
    """
    if os.path.isabs(path):
        return path
    try:
        if sys.platform == "darwin":
            directory = os.fsdecode(fcntl.fcntl(dir_fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0"))
        else:
            directory = _os_readlink(f"/proc/self/fd/{dir_fd}")
    except OSError:
        _raise_access(path)
    return os.path.join(directory, path)


def _check_dir_fd(path: str, dir_fd: int, *, write: bool, learn: bool = True) -> None:
    """Apply the rules to ``path`` relative to ``dir_fd``; the call keeps both unchanged."""
    target = _dir_fd_path(path, dir_fd)
    remapped, rule = _apply_dest_to_src_rules(target, write=write)
    if rule:
        _raise_ignore(path, rule)
    if not remapped:
        if is_learning_mode():
            if learn:
                add_learning_rule(LearnFileRule(Path(target), write))
        else:
            _raise_access(target)


# %% Generic wrapper
# def _wrap_empty(func: [...,Any]) -> Callable[...,Any]:
#     return func


# def _wrap_reload_module(func: Callable[...,Any], *, name: str) -> ModuleType:
#     # Use _f(_wrap_reload_module, name="io") to refresh a module in another module
#     import sys
#     return sys.modules[name]


def _wrap_buitins_open(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        file: str | int | None,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Callable[..., Any] | None = None,
    ) -> Any:
        if isinstance(file, int):
            # A descriptor names no path, so there is nothing for the rules to match:
            # the call that opened it went through the guard already. Rewriting it as a
            # path would also break `closefd=False`, which open() only accepts on a
            # descriptor -- `open(2, "w", closefd=False)` died on "Cannot use
            # closefd=False with file name". Same passthrough as _wrap_filename.
            return func(
                file,
                mode=mode,
                buffering=buffering,
                encoding=encoding,
                errors=errors,
                newline=newline,
                closefd=closefd,
                opener=opener,
            )
        if isinstance(file, _DirEntry):
            file = str(file)

        need_to_write = mode is not None and ("w" in mode or "a" in mode or "x" in mode or "+" in mode)
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


# def _wrap_test(func: Callable[...,Any]) -> Callable[...,Any]:
#     @functools.wraps(func)
#     def wrapper(
#             *args,**kwargs
#     ) -> Any:
#         return func(*args, **kwargs)
#
#     return wrapper
#


def _wrap_filename(func: Callable[..., Any], *, write: bool, learn: bool = True) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
        *args: Any,
        **kwargs: dict[str, Any],
    ) -> Any:

        # Detect call from posixpath
        if isinstance(file, int):
            return func(file, *args, **kwargs)
        if isinstance(file, bytes):
            file = os.fsdecode(file)
        file = cast(str, file)
        dir_fd = kwargs.get("dir_fd")
        if dir_fd is not None:
            _check_dir_fd(file, cast(int, dir_fd), write=write, learn=learn)
            return func(file, *args, **kwargs)
        remapped, rule = _apply_dest_to_src_rules(file, write=write)
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


def _body_two_filenames(
    func: Callable[..., Any],
    in_write: bool,
    out_write: bool,
    src: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    dest: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    *args: Any,
    **kwargs: dict[str, Any],
) -> Any:
    # Detect call from posixpath
    if isinstance(src, bytes):
        src = os.fsdecode(src)
    if isinstance(dest, bytes):
        dest = os.fsdecode(dest)
    src = cast(str, src)
    dest = cast(str, dest)
    src_dir_fd = kwargs.get("src_dir_fd")
    dst_dir_fd = kwargs.get("dst_dir_fd")
    if src_dir_fd is not None:
        _check_dir_fd(src, cast(int, src_dir_fd), write=in_write)
        remapped_src: str | None = src
        rule1 = None
    else:
        remapped_src, rule1 = _apply_dest_to_src_rules(src, write=in_write)

    if dst_dir_fd is not None:
        _check_dir_fd(dest, cast(int, dst_dir_fd), write=out_write)
        remapped_dest: str | None = dest
        rule2 = None
    else:
        remapped_dest, rule2 = _apply_dest_to_src_rules(dest, write=out_write)

    if rule1:
        _raise_ignore(src, rule1)
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


def _wrap_two_filenames(
    func: Callable[..., Any], *, in_write: bool = False, out_write: bool = True
) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        src: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        dest: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *args: Any,
        **kwargs: dict[str, Any],
    ) -> Any:
        return _body_two_filenames(func, in_write, out_write, src, dest, *args, **kwargs)

    return wrapper


def _wrap_shutil_copytree(
    func: Callable[..., Any],
) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        src: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        dest: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *args: Any,
        **kwargs: dict[str, Any],
    ) -> Any:
        try:
            _ = _check_alias.set(False)
            return _body_two_filenames(func, False, True, src, dest, *args, **kwargs)
        finally:
            _ = _check_alias.set(True)

    return wrapper


# def _wrap_os_path_realpath(func: Callable[...,Any]) -> Callable[...,Any]:
#     @functools.wraps(func)
#     def wrapper(file: str | bytes | os.PathLike) -> Any:
#         # Detect call from posixpath
#         file = cast(str, file)
#         remapped, rule = _apply_dest_to_src_rules(cast(str, file), write=False)
#         if rule:
#             _raise_ignore(file, rule)
#         if not remapped:
#             if is_learning_mode():
#                 add_learning_rule(LearnFileRule(Path(file), False))
#                 remapped = file
#                 pass
#             else:
#                 _raise_access(file)
#         return func(remapped)
#
#     return wrapper


def _wrap_os_stat(func: Callable[..., Any], *, write: bool) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> Any:
        if isinstance(path, int):
            return func(path=path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if isinstance(path, _DirEntry):
            path = str(path)
        if dir_fd is not None:
            _check_dir_fd(cast(str, path), dir_fd, write=write)
            return func(path=path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if _check_alias.get():
            remapped, rule = _apply_dest_to_src_rules(cast(str, path), write=write, accept_dest=_check_alias.get())
        else:
            remapped, rule = str(path), None
        if rule:
            _raise_ignore(path, rule)
        if not remapped:
            if is_learning_mode():
                # add_learning_rule(LearnFileRule(Path(path), write))
                remapped = str(path)
            else:
                _raise_access(str(path))
        return func(path=remapped, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    return wrapper


def _wrap_os_path_samefile(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        f1: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        f2: str | bytes | os.PathLike[str] | os.PathLike[bytes],
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
        remapped_src, rule1 = _apply_dest_to_src_rules(f1, write=False)
        if rule1:
            _raise_ignore(f1, rule1)
        remapped_dest = None
        if remapped_src is not None:
            remapped_dest, rule2 = _apply_dest_to_src_rules(f2, write=False)
            if rule2:
                _raise_ignore(f2, rule2)
        if remapped_dest is None:
            remapped_dest = f2
        return func(str(remapped_src), str(remapped_dest))

    return wrapper


def _wrap_os_chdir(func: Callable[..., Any], *, write: bool) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
    ) -> None:

        # Detect call from posixpath
        if isinstance(path, int):
            return func(path)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if isinstance(path, _DirEntry):
            path = str(path)
        path = cast(str, path)

        if isinstance(path, int):
            return func(path)
        new_dir = _dir_path(os.fspath(path))
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


def _wrap_pathlib_Path_glob(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        self: Any,
        pattern: str,
        *,
        case_sensitive: bool | None = None,
        recurse_symlinks: bool = False,
    ) -> Iterator["Path"]:

        remapped, rule = _apply_dest_to_src_rules(self, write=False)
        if not _check_alias.get():
            remapped = str(self)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(self, write=False))
                remapped = self
            else:
                _raise_access(self)

        def filter(it: Iterator[Path]) -> Iterator[Path]:
            abs_remapper = _os_path_realpath(remapped)
            check_alias = _check_alias.get()
            while True:
                try:
                    if check_alias:
                        _ = _check_alias.set(False)
                    name = next(it)
                    if check_alias:
                        _ = _check_alias.set(True)
                    remapped_filter, rule = _apply_src_to_dest_rules(str(name), accept_src=False, accept_dest=True)
                    if remapped_filter:
                        if not os.path.isabs(str(self)):
                            remapped_filter = remapped_filter[len(abs_remapper) + 1 :]
                        if remapped_filter == "":
                            remapped_filter = "."
                        # yield Path(remapped_filter).relative_to(self)
                        yield Path(remapped_filter)
                except StopIteration:
                    _ = _check_alias.set(True)
                    break

        extra: dict[str, Any] = {}
        if sys.version_info[:2] >= (3, 12):
            extra = {"case_sensitive": case_sensitive}
        if sys.version_info[:2] >= (3, 13):
            extra = {"recurse_symlinks": recurse_symlinks}

        if remapped and _check_alias.get():
            _ = _check_alias.set(False)
            do_filter = filter(
                func(
                    Path(remapped),
                    pattern=pattern,
                    **extra,
                )
            )
            _ = _check_alias.set(True)
        else:
            do_filter = filter(
                func(
                    self,
                    pattern=pattern,
                    **extra,
                )
            )
        return do_filter

    return wrapper


# %% os wrapper
def _wrap_os_open(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
        flags: int,
        mode: int = 0o777,
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
        path = cast(str, path)
        if dir_fd is not None:
            if isinstance(flags, int):
                write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
                write_flags |= getattr(os, "O_TMPFILE", 0)
                need_to_write = bool(flags & write_flags)
            else:
                need_to_write = True
            _check_dir_fd(path, dir_fd, write=need_to_write)
            return func(path=path, flags=flags, mode=mode, dir_fd=dir_fd)
        if isinstance(flags, int):
            # O_TRUNC empties a file even opened O_RDONLY, and O_CREAT creates one.
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
            write_flags |= getattr(os, "O_TMPFILE", 0)
            need_to_write = bool(flags & write_flags)
            remapped, rule = _apply_dest_to_src_rules(path, write=need_to_write)
            if remapped is None:
                if is_learning_mode():
                    add_learning_rule(LearnFileRule(Path(path), need_to_write))
                    remapped = path
                else:
                    _raise_access(path)
        return func(path=remapped, flags=flags, mode=mode, dir_fd=dir_fd)

    return wrapper


def _wrap_os_access(func: Callable[..., Any], *, write: bool) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
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
        path = cast(str, path)
        if dir_fd is not None:
            try:
                _check_dir_fd(path, dir_fd, write=write)
            except (RuleFileNotFoundError, RulePermissionError):
                return False
            return func(
                path=path,
                mode=mode,
                dir_fd=dir_fd,
                effective_ids=effective_ids,
                follow_symlinks=follow_symlinks,
            )
        remapped, rule = _apply_dest_to_src_rules(path, write=write)
        if rule:
            return False
        if is_learning_mode():
            # Learning mode observes, it does not remap: the rules that would
            # say where to remap to are still being discovered.
            return func(
                path=path,
                mode=mode,
                dir_fd=dir_fd,
                effective_ids=effective_ids,
                follow_symlinks=follow_symlinks,
            )
        if not remapped:
            # os.access answers a question, it opens nothing, and its
            # documented contract is a bool: callers write
            # ``if os.access(p, R_OK):``, this package included
            # (generate_rules below, guard_socket's hosts-file probe).
            # Raising would break them, so a path no rule exposes is reported
            # inaccessible, exactly like the ignore= rule above. Answering for
            # real would instead make os.access an existence and permission
            # oracle over the whole host filesystem.
            return False
        return func(
            path=remapped,
            mode=mode,
            dir_fd=dir_fd,
            effective_ids=effective_ids,
            follow_symlinks=follow_symlinks,
        )

    return wrapper


def _wrap_os_getcwd(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper() -> str:
        # Detect call from posixpath
        dir: str = func()
        new_dir = _dir_path(os.fsdecode(os.fspath(dir)))

        remapped, rule = _apply_src_to_dest_rules(new_dir, accept_src=True)
        if remapped is None:
            if is_learning_mode():
                # add_learning_rule(LearnFileRule(Path(new_dir), False))
                remapped = new_dir
            else:
                _raise_access(new_dir)

        if remapped.endswith(os.path.sep + "."):
            remapped = remapped[:-2]
        if remapped != os.path.sep and remapped.endswith(os.path.sep):
            remapped = remapped[:-1]
        return str(remapped)

    return wrapper


def _wrap_os_getcwdb(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper() -> bytes:
        # Detect call from posixpath
        dir: bytes = func()
        new_dir: str = _dir_path(os.fspath(dir.decode()))

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
        return remapped.encode(sys.getfilesystemencoding())

    return wrapper


def _wrap_os_listdir(func: Callable[..., list[str]]) -> Callable[..., list[str]]:
    @guard_wraps(func)
    def wrapper(
        path: str | os.PathLike[str] | os.PathLike[bytes] | bytes | int | None = None,
    ) -> list[str]:

        if isinstance(path, int):
            return func(path=path)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if path is None:
            path = "."
        path = cast(str, path)
        if new_path_and_rule := _apply_dest_to_src_rules(path, write=False, accept_src=False, accept_dest=True):
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
                    remapped_file, _ = _apply_dest_to_src_rules(full_path, write=False, accept_dest=True)
                    if remapped_file and remapped_file not in filtered:
                        filtered.append(entry)
                return filtered
            else:
                return entries
        else:
            return []

    return wrapper


def _wrap_os_readlink(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
    ) -> str:

        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        if dir_fd is not None:
            _check_dir_fd(path, dir_fd, write=False)
            target = func(path=path, dir_fd=dir_fd)
            if not target.startswith(os.path.sep):
                target = os.path.join(os.path.dirname(_dir_fd_path(path, dir_fd)), target)
            remapped, rule = _apply_src_to_dest_rules(target)
            if rule:
                _raise_ignore(path, rule)
            if not remapped:
                _raise_access(path)
            return remapped
        remapped_first, rule = _apply_dest_to_src_rules(path, write=False)
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


def _wrap_os_symlink(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        src: StrOrBytesPath,
        dst: StrOrBytesPath,
        target_is_directory: bool = False,
        *,
        dir_fd: int | None = None,
    ) -> Any:

        if isinstance(src, int) or isinstance(dst, int):
            return func(
                src=src,
                dst=dst,
                target_is_directory=target_is_directory,
                dir_fd=dir_fd,
            )
        if isinstance(src, bytes):
            src = os.fsdecode(src)
        if isinstance(dst, bytes):
            dst = os.fsdecode(dst)
        src = cast(str, src)
        dst = cast(str, dst)
        if dir_fd is not None:
            _check_dir_fd(dst, dir_fd, write=True)
            target = src if os.path.isabs(src) else os.path.join(os.path.dirname(_dir_fd_path(dst, dir_fd)), src)
            checked_src, src_rule = _apply_dest_to_src_rules(target, write=False, accept_src=True)
            if src_rule:
                _raise_ignore(src, src_rule)
            if not checked_src and not is_learning_mode():
                _raise_access(src)
            if not checked_src:
                add_learning_rule(LearnFileRule(Path(target), False))
            return func(src, dst, target_is_directory=target_is_directory, dir_fd=dir_fd)
        remapped, rule = _apply_dest_to_src_rules(dst, write=True)
        if rule:
            _raise_ignore(dst, rule)
        if not remapped:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(dst), True))
                remapped = dst
            else:
                _raise_access(dst)
        # The link target must be checked whatever its form: a relative
        # target such as "../../etc/passwd" escapes the exposed directories
        # exactly like an absolute one. A relative target resolves against
        # the link directory, not the current one.
        target = src if os.path.isabs(src) else os.path.join(os.path.dirname(remapped), src)
        checked_src, src_rule = _apply_dest_to_src_rules(target, write=False, accept_src=True)
        if src_rule:
            _raise_ignore(src, src_rule)
        if not checked_src:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(target), False))
            else:
                _raise_access(src)

        # ``src`` is passed through unchanged: rewriting it would turn a
        # relative link into an absolute one and change what the link means.
        return func(
            src,
            remapped,
            target_is_directory=target_is_directory,
            dir_fd=dir_fd,
        )

    return wrapper


def _wrap_os_unlink(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(path: StrOrBytesPath, *, dir_fd: int | None = None) -> None:
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        if dir_fd is not None:
            _check_dir_fd(path, dir_fd, write=True)
            return func(path=path, dir_fd=dir_fd)
        remapped, rule = _apply_dest_to_src_rules(path, write=True)
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


def _wrap_os_rmdir(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(path: StrOrBytesPath, *, dir_fd: int | None = None) -> None:
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        if dir_fd is not None:
            _check_dir_fd(path, dir_fd, write=True)
            return func(path=path, dir_fd=dir_fd)
        remapped, rule = _apply_dest_to_src_rules(path, write=True)
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


class _ScanDirContextManager(Iterator[os.DirEntry[str]]):
    """
    A context manager that wraps os.scandir and implements the context manager kind.
    """

    __slots__ = ("directory", "real_directory", "scanner")

    def __init__(self, directory: str):
        super().__init__()
        self.directory = directory
        if _check_alias.get():
            new_path, rule = _apply_dest_to_src_rules(
                directory,
                write=False,
            )
        else:
            new_path, rule = directory, None
        if rule:
            _raise_ignore(directory, rule)
        if new_path is None:
            if is_learning_mode():
                add_learning_rule(LearnFileRule(Path(directory).absolute(), False))
                new_path = directory
            else:
                _raise_access(directory)
        self.real_directory = new_path
        self.scanner: Any = None

    def close(self) -> None:
        if self.scanner and hasattr(self.scanner, "close"):
            self.scanner.close()

    def __enter__(self) -> "_ScanDirContextManager":
        """
        Enter the context manager, opening the scandir iterator.
        """
        if self.scanner is not None:
            return self
        self.scanner = _scandir(self.real_directory)
        _ = self.scanner.__enter__()
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
            try:
                return self.scanner.__exit__(exc_type, exc_val, exc_tb)
            finally:
                self.scanner = None
        return False  # Don't suppress exceptions

    def __iter__(self) -> Iterator[os.DirEntry[str]]:
        """h
        Make the context manager iterable.
        """
        if is_learning_mode() and OPTIMIZE:
            if self.scanner is None:
                self.__enter__()
            return cast(Any, self.scanner).__iter__()  # type: ignore[union-attr]
        return self

    def __next__(self) -> os.DirEntry[str]:
        """
        Get the next file entry from the directory.
        """
        # Support ``for x in os.scandir(path)`` without ``with`` (pytest tmp_path,
        # CPython PEP 471 behaviour): iteration must open the underlying scanner.
        if self.scanner is None:
            self.__enter__()

        if not self.real_directory:
            raise StopIteration

        while True:
            try:
                while True:
                    entry: os.DirEntry[str] = self.scanner.__next__()  # type: ignore
                    if _check_alias.get():
                        dest_path, rule = _apply_src_to_dest_rules(entry.path, accept_src=False, accept_dest=True)
                    else:
                        dest_path, rule = entry.path, None
                    if rule:
                        pass  # Ignore
                    elif dest_path is not None:
                        _entry = _DirEntry(entry, dest_path)
                        return cast(os.DirEntry[str], _entry)
            except StopIteration:
                raise


def _wrap_os_scandir(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Wrap os.scandir to handle exceptions and return an iterator or None.
    """

    @guard_wraps(func)
    def wrapper(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | None = None,
    ) -> Iterator[os.DirEntry[str]]:
        if path is None:
            path = "."
        if isinstance(path, int):
            _check_dir_fd(".", path, write=False)
            return func(path)
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = cast(str, path)
        return _ScanDirContextManager(path)

    return wrapper


# %% io wrapper


def _wrap_io_open(func: Callable[..., Any]) -> Callable[..., Any]:
    @guard_wraps(func)
    def wrapper(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
        mode: str | None = "r",
        buffering: int | None = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Callable[..., Any] | None = None,
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
        if isinstance(file, bytes):
            file = os.fsdecode(file)
        file = str(file)
        need_to_write = mode is not None and ("w" in mode or "a" in mode or "x" in mode or "+" in mode)
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


def _wrap_io_FileIO(func: Callable[..., Any]) -> Callable[..., Any]:
    from io import FileIO as io_FileIO

    class FileIO(io_FileIO):
        def __new__(
            cls,
            file: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
            mode: str | None = "r",
            closefd: bool = True,
            opener: Callable[..., Any] | None = None,
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
            if isinstance(file, bytes):
                file = os.fsdecode(file)
            file = str(file)
            need_to_write = mode is not None and ("w" in mode or "a" in mode or "x" in mode or "+" in mode)
            remapped, rule = _apply_dest_to_src_rules(file, write=need_to_write)
            if rule:
                _raise_ignore(file, rule)
            if remapped is None:
                if is_learning_mode():
                    add_learning_rule(LearnFileRule(Path(file).absolute(), need_to_write))
                    remapped = file
                else:
                    _raise_access(file)
            instance = io_FileIO.__new__(io_FileIO)
            instance.__init__(  # type: ignore[misc]
                file=remapped,
                mode=mode,
                closefd=closefd,
                opener=opener,
            )
            return instance

    return FileIO


# %% _os
def _wrap__io(module: ModuleType) -> ModuleType:
    if "io" in sys.modules:
        del sys.modules["io"]
    import io

    assert io.open.__pysandbox__  # type: ignore [attr-defined]
    return io


_default_rules: dict[str, Callable[..., Any]] = {
    "os.chdir": _f(_wrap_os_chdir, write=False),
    # ALLOW os.fchdir
    "os.getcwd": _f(_wrap_os_getcwd),
    "os.getcwdb": _f(_wrap_os_getcwdb),
    # ALLOW os.fdopen
    "os.open": _f(_wrap_os_open),
    "os.access": _f(_wrap_os_access, write=False),
    "os.chmod": _f(_wrap_filename, write=True),
    # `posix.chroot` was the one twin spelled out here; `_twin_rules` now
    # mirrors every entry below, so the hand-written line is redundant.
    "os.chroot": _f(_wrap_filename, write=False),
    "os.link": _f(_wrap_two_filenames),
    "os.listdir": _f(_wrap_os_listdir),
    "os.mkdir": _f(_wrap_filename, write=True),
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
    # These run code outside the patched interpreter, so no file or
    # socket rule applies to what they start. They are guarded by
    # guard_api (SENSITIVE_API, categories "process-exec" and
    # "process-control"), denied by default. Do not gate them on a
    # module import right: that would be a pseudo-import.
    # ALLOW os.getenv
    # ALLOW os.supports_bytes_environ
    # ALLOW os.environb
    # ALLOW os.getenvb
    # DENY os.putenv, os.unsetenv (see guard_envs)
    # %% high level access
    "io.open": _f(_wrap_io_open),
    "io.open_code": _f(_wrap_filename, write=False),
    "io.FileIO": _f(_wrap_io_FileIO),
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
    # "os.path.realpath": _f(_wrap_filename, write=False, learn=False),
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
    "pathlib.Path.rglob": _f(_wrap_pathlib_Path_glob),
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
    "shutil.copytree": _f(_wrap_shutil_copytree),
    # ALLOW shutil.disk_usage
    # ALLOW shutil.make_archive
    # ALLOW shutil.move
    # "shutil.rmtree": _f(_wrap_filename, write=True),
    # ALLOW shutil.which
    # builtins
    "builtins.open": _f(_wrap_buitins_open),
}


def _wrap_pathlib_3_10(normal_accessor: Any) -> Callable[..., Any]:
    # set to the patched version
    normal_accessor.stat = os.stat
    normal_accessor.open = io.open
    normal_accessor.listdir = os.listdir
    normal_accessor.scandir = os.scandir
    normal_accessor.chmod = os.chmod
    normal_accessor.mkdir = os.mkdir
    normal_accessor.unlink = os.unlink
    if hasattr(os, "link"):
        normal_accessor.link = os.link
    normal_accessor.rmdir = os.rmdir
    normal_accessor.rename = os.rename
    normal_accessor.replace = os.replace
    if hasattr(os, "symlink"):
        normal_accessor.symlink = os.symlink
    if hasattr(os, "readlink"):
        normal_accessor.readlink = os.readlink
    normal_accessor.getcwd = os.getcwd
    normal_accessor.realpath = os.path.realpath
    return normal_accessor


def patch_rules(learn: bool) -> dict[str, Callable[..., Any]]:
    """Provide file system patching rules for guard activation.

    Returns:
        Dictionary of file system module patches.
    """
    rules: dict[str, Callable[..., Any]] = dict(_default_rules)
    if sys.version_info[:2] == (3, 10):
        rules |= {"pathlib._normal_accessor": _f(_wrap_pathlib_3_10)}
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
    rules |= _twin_rules(rules)
    return rules


def _twin_rules(os_rules: dict[str, Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
    """Mirror every ``os.*`` rule onto the module `os` actually re-exports.

    `os` does not implement these calls: it re-exports them from `posix`
    (Linux, macOS and every other POSIX platform) or `nt` (Windows), by
    identity -- ``os.open is posix.open`` holds until something patches one of
    them. Patching only `os.open` therefore leaves the original one
    ``import posix`` away, which is not a hostile manoeuvre: `posix` is
    documented, importable, and what `os` itself uses.

    Measured on Linux before writing this: with the twins absent, ``open()``
    on a path outside the exposed directory raised RuleFileNotFoundError while
    ``posix.open()`` on the same path went all the way to the kernel.

    The `nt` rows are shipped unexercised -- no Windows machine ran them. They
    cost nothing where they do not apply: an absent module never reaches
    `activate_guard_import`, which only walks what `sys.modules` holds.
    """
    twin_name = "nt" if sys.platform == "win32" else "posix"
    try:
        twin = importlib.import_module(twin_name)
    except ImportError:  # pragma: no cover - `posix` is always there on POSIX
        return {}

    twins: dict[str, Callable[..., Any]] = {}
    for key, factory in os_rules.items():
        if not key.startswith("os."):
            continue
        attribute = key[len("os.") :]
        # Mirror only what the twin actually provides: `os` implements a few of
        # these itself (`os.walk`), and a rule on a name the module does not
        # have would post a patch on nothing.
        if hasattr(twin, attribute):
            twins[f"{twin_name}.{attribute}"] = factory
    return twins


# %%
def activate_guard(rules: FilesRules) -> None:
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
        # "" prefixes every path, on every drive; "/" covers POSIX only.
        _rules = (FSExposeRule(path="", write=True, config=ConfigLine("pytest", Path(), 0)),)
