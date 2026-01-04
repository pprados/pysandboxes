import sys

import inspect
import io

import logging

import builtins
import fnmatch
import functools
import os
import typing
from types import TracebackType
from typing import Iterator
from typing import List, Callable, Optional, Union

logger = logging.getLogger(__name__)

# TODO: injecter les mappings dans les filtres de répertoires si c'est présent ? n'accepte pas mapping phantome ?

_white_list =['<frozen posixpath>', '<frozen genericpath>', "pathlib/_local.py"]

# Internal representation of a rule
class ParserRule:
    def __init__(self, rule_type: str, pattern: str, replacement: Optional[str] = None):
        self.rule_type = rule_type  # 'bind' or 'ignore'
        self.pattern = pattern
        self.replacement = replacement


def _parse_rule(arguments: List[str]) -> List[ParserRule]:
    """
    Parses rule strings into internal ParserRule objects.
    Supports --bind=src,dest and --ignore=glob_pattern.
    """
    rules: List[ParserRule] = []
    for arg in arguments:
        if arg.startswith("--bind="):  # TODO: --ro-bind
            value = arg[len("--bind="):]
            try:
                src, dest = value.split(",", 1)
                rules.append(ParserRule("bind", src, dest))
            except ValueError:
                raise ValueError(f"Invalid bind rule: {arg}")
        elif arg.startswith("--ignore="):
            pattern = arg[len("--ignore="):]
            rules.append(ParserRule("ignore", pattern))
        else:
            raise ValueError(f"Unknown rule: {arg}")
    return rules


# Internal state for the file filter
_rules: List[ParserRule] = []

_os_path_realpath=os.path.realpath
# Helper to resolve symlinks and apply rules
def _apply_rules(path: str) -> Optional[str]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    real_path = _os_path_realpath(path,strict=True)
    original_path = path

    for rule in _rules:
        if rule.rule_type == "ignore":
            if fnmatch.fnmatch(original_path, rule.pattern) or fnmatch.fnmatch(
                    real_path, rule.pattern):
                return None
        elif rule.rule_type == "bind":
            if real_path.startswith(rule.pattern):
                relative = os.path.relpath(real_path, rule.pattern)
                new_path = os.path.join(rule.replacement, relative)
                return new_path
    return path


# Helper to resolve symlinks and apply rules
def _apply_inverse_rules(path: str) -> Optional[str]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    fake_path = os.path.abspath(path)
    original_path = path

    for rule in _rules:
        if rule.rule_type == "ignore":
            if fnmatch.fnmatch(original_path, rule.pattern) or fnmatch.fnmatch(
                    fake_path, rule.pattern):
                return None
        elif rule.rule_type == "bind":
            if fake_path.startswith(rule.replacement):
                relative = os.path.relpath(fake_path, rule.replacement)
                new_path = os.path.join(rule.pattern, relative)
                return new_path
    return path


import inspect


def _wrap_filename(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike, int], *args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename=None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(file, *args, **kwargs)
        print(f"{filename=}")  # FIXME
        if isinstance(file, int):
            return func(file, *args, **kwargs)
        remapped = _apply_inverse_rules(os.fspath(file))
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return func(remapped, *args, **kwargs)

    return wrapper


def _wrap_getcwd(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename=None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(*args, **kwargs)
        file= func(*args, **kwargs)
        remapped = _apply_rules(os.fspath(file))
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        if remapped.endswith(os.path.sep+"."):
            remapped=remapped[:-2]
        return str(remapped)

    return wrapper

def _wrap_listdir(func: Callable[..., List[str]]) -> Callable[..., List[str]]:
    @functools.wraps(func)
    def wrapper(path: Union[str, bytes, os.PathLike] = '.') -> List[str]:
        if new_path := _apply_inverse_rules(path):
            entries = func(new_path)
            filtered: List[str] = []
            for entry in entries:
                full_path = os.path.join(path, entry)
                if _apply_inverse_rules(full_path) is not None:
                    filtered.append(entry)
            return filtered
        else:
            raise FileNotFoundError(f"Access to '{path}' is ignored by rule")

    return wrapper

def _wrap_two_filenames(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(src: Union[str, bytes, os.PathLike],
                dest: Union[str, bytes, os.PathLike],
                *args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename=None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(src,dest, *args, **kwargs)
        remapped_src = _apply_inverse_rules(os.fspath(src))
        remapped_dest = _apply_inverse_rules(os.fspath(dest))
        func(remapped_src,remapped_dest, *args, **kwargs)

    return wrapper
def _wrap_readlink(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike], *args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename=None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(file, *args, **kwargs)
        remapped_first = _apply_inverse_rules(os.fspath(file))
        remapped = func(remapped_first, *args, **kwargs)
        if not remapped.startswith(os.path.sep):
            remapped =os.path.dirname(remapped_first)+"/"+remapped
        remapped = _apply_rules(remapped)
        if not remapped:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return remapped

    return wrapper

# %%
from os import scandir as _scandir

class _ScanDirContextManager:
    """
    A context manager that wraps os.scandir and implements the context manager protocol.
    """

    def close(self):
        if self.scanner:
            self.scanner.close()

    def __init__(self, directory: str):
        self.directory = directory
        self.real_directory = _apply_inverse_rules(directory)
        self.scanner = None

    def __enter__(self) -> 'ScanDirContextManager':
        """
        Enter the context manager, opening the scandir iterator.
        """
        try:
            self.scanner = _scandir(self.real_directory)
            self.scanner.__enter__()
            return self
        except Exception as e:
            self.error = e
            print(f"Error scanning directory {self.directory}: {e}")  # FIXME
            return self

    def __exit__(self, exc_type: Optional[typing.Type[BaseException]],
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
        return self

    def __next__(self) -> os.DirEntry:
        """
        Get the next file entry from the directory.
        """
        if self.scanner is None:
            raise StopIteration

        while True:
            try:
                while True:
                    entry = next(self.scanner)
                    real_path = _apply_rules(entry.path)
                    if real_path:
                        class _DirEntry:
                            pass

                        _entry = _DirEntry()
                        _entry.name = entry.name
                        _entry.path = real_path
                        return _entry
            except StopIteration:
                raise
            except Exception as e:
                print(f"Error iterating over {self.directory}: {e}")
                raise StopIteration


def _wrap_scandir(func: Callable) -> Callable:
    """
    Wrap os.scandir to handle exceptions and return an iterator or None.
    """

    @functools.wraps(func)
    def wrapper(path: Union[str, bytes, os.PathLike] = '.') -> Iterator:
        return _ScanDirContextManager(path)

    return wrapper


from pathlib import Path as _Path, Path
from pathlib import Path as _Path
_Path_glob = _Path.glob

def _wrap_pathlib(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike], *args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename=None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(file, *args, **kwargs)
        remapped = _apply_inverse_rules(os.fspath(file))
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return func(Path(remapped), *args, **kwargs)

    return wrapper

def _wrap_pathlib_glob(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self, glob: str) -> Iterator:
        if new_path := _apply_inverse_rules(self):
            return [_apply_rules(os.path.dirname(p)) +os.path.sep+ os.path.basename(p) for p in
                     _Path_glob(_Path(new_path), glob) if _apply_rules(p) is not None]
        else:
            raise FileNotFoundError(f"Access to '{self}' is ignored by rule")

    return wrapper


if "PYTEST_RUN_CONFIG" in os.environ:
    _remember={
        "builtins.open":builtins.open,
        "io.open":io.open,
        "os.chdir":os.chdir,
        "os.getcwd":os.getcwd,
        "os.getcwdb":os.getcwdb,
        "os.open":os.open,
        "os.access":os.access,
        "os.chroot":os.chroot,
        "os.chmod":os.chmod,
        "os.link":os.link,
        "os.listdir":os.listdir,
        "os.mkdir":os.mkdir,
        "os.readlink":os.readlink,
        "os.remove":os.remove,
        "os.rename":os.rename,
        "os.replace":os.replace,
        "os.rmdir":os.rmdir,
        "os.scandir":os.scandir,
        "os.stat":os.stat,
        "os.lstat":os.lstat,
        "os.symlink":os.symlink,
        "os.truncate":os.truncate,
        "os.unlink":os.unlink,
        "os.utime":os.utime,

        "pathlib.Path.glob":_Path.glob, # TODO: ajouter reste
        }
    if sys.platform != "win32" and sys.platform != "linux":
        _remember |= {
            "os.chflags": os.chflags,
            "os.lchflags": os.lchflags,
            "os.lchmod": os.lchmod,
        }
    if sys.platform != "win32":
        _remember |= {
            "os.chown": os.chown,
            "os.lchown": os.lchown,
        }

    def deactivate_guard_files():
        builtins.open = _remember["builtins.open"]
        io.open = _remember["io.open"]
        os.chdir = _remember["os.chdir"]
        os.getcwd = _remember["os.getcwd"]
        os.getcwdb = _remember["os.getcwdb"]
        os.open = _remember["os.open"]
        os.access = _remember["os.access"]
        os.chroot = _remember["os.chroot"]
        os.chmod = _remember["os.chmod"]
        os.link = _remember["os.link"]
        os.listdir = _remember["os.listdir"]
        os.mkdir = _remember["os.mkdir"]
        os.readlink = _remember["os.readlink"]
        os.remove = _remember["os.remove"]
        os.rename = _remember["os.rename"]
        os.replace = _remember["os.replace"]
        os.rmdir = _remember["os.rmdir"]
        os.scandir = _remember["os.scandir"]
        os.stat = _remember["os.stat"]
        os.lstat = _remember["os.lstat"]
        os.symlink = _remember["os.symlink"]
        os.truncate = _remember["os.truncate"]
        os.unlink = _remember["os.unlink"]
        os.utime = _remember["os.utime"]
        if sys.platform != "win32" and sys.platform != "linux":
            os.chflags = _remember["os.chflags"]
            os.lchflags = _remember["os.lchflags"]
            os.lchmod = _remember["os.lchmod"]
        if sys.platform != "win32":
            os.chown = _remember["os.chown"]
            os.lchown = _remember["os.lchown"]

        _Path.glob = _remember["pathlib.Path.glob"]

        global _rules
        _rules = []

def activate_guard_files(rules: List[str]) -> None:
    """
    Initializes the file access filter with the given rule list.
    Overrides built-in open and os.listdir functions.
    """
    import sys
    sys.setrecursionlimit(2000)  # FIXME

    global _rules
    install_wrapper = not _rules
    _rules = _parse_rule(rules)

    if install_wrapper:
        builtins.open = _wrap_filename(builtins.open)  # type: ignore

        import io
        io.open = _wrap_filename(io.open)  # type: ignore
        # FIXME io.open_code = _wrap_filename(io.open_code)  # type: ignore
        # io.FileIO = _wrap_filename(io.FileIO)  # type: ignore

        import os
        os.chdir = _wrap_filename(os.chdir)
        # NO os.fchdir
        os.getcwd = _wrap_getcwd(os.getcwd)
        os.getcwdb = _wrap_getcwd(os.getcwdb)
        # NO os.fdopen
        # NO os.tmpfile
        os.open = _wrap_filename(os.open)
        os.access= _wrap_filename(os.access)
        if sys.platform != "win32" and sys.platform != "linux":
            os.chflags = _wrap_filename(os.chflags)
            os.lchflags= _wrap_filename(os.lchflags)
            os.lchmod= _wrap_filename(os.lchmod)
        os.chroot= _wrap_filename(os.chroot)
        os.chmod= _wrap_filename(os.chmod)
        if sys.platform != "win32":
            os.chown = _wrap_filename(os.chown)
            os.lchown = _wrap_filename(os.lchown)
        os.link = _wrap_filename(os.link)
        os.listdir = _wrap_listdir(os.listdir)
        os.mkdir = _wrap_filename(os.mkdir)
        # DENY os.mkfifo
        # DENY os.mknod
        os.readlink = _wrap_readlink(os.readlink)
        os.remove = _wrap_filename(os.remove)
        # NO os.removedirs= _wrap_filename(os.removedirs)
        os.rename = _wrap_two_filenames(os.rename)
        # NO os.renames = _wrap_two_filenames(os.renames)
        os.replace = _wrap_two_filenames(os.replace)
        os.rmdir = _wrap_filename(os.rmdir)
        os.scandir = _wrap_scandir(os.scandir)
        os.stat = _wrap_filename(os.stat)
        os.lstat = _wrap_filename(os.lstat)
        # NO os.stat_float_times
        os.symlink = _wrap_filename(os.symlink)
        os.truncate = _wrap_filename(os.truncate)
        os.unlink = _wrap_filename(os.unlink)
        os.utime = _wrap_filename(os.utime)
        # NO os.walk = _wrap_filename(os.walk)

        # %%
        # os.path.basename(path)
        # os.path.abspath(path)
        # os.path.exists(path)
        # os.path.islink(path)
        # os.path.isdir(path)
        # os.path.isfile(path)
        # os.path.samefile(path1, path2)
        # os.path.realpath(path)
        # os.path.expanduser(path) → transforme ~ en /home/...
        # os.path.normpath(path)

        import pathlib
        # OK pathlib.Path.open = _wrap_filename(pathlib.Path.open)  # type: ignore
        pathlib.Path.read_text = _wrap_pathlib(pathlib.Path.read_text)  # type: ignore
        # OK pathlib.Path.read_bytes = _wrap_filename(pathlib.Path.read_bytes)  # type: ignore
        pathlib.Path.write_text = _wrap_pathlib(pathlib.Path.write_text)  # type: ignore
        # OK pathlib.Path.write_bytes = _wrap_filename(pathlib.Path.write_bytes)  # type: ignore
        # OK pathlib.Path.iterdir = _wrap_filename(pathlib.Path.iterdir)  # type: ignore
        pathlib.Path.glob = _wrap_pathlib_glob(pathlib.Path.glob)  # type: ignore
        # pathlib.Path.rglob = _wrap_filename(pathlib.Path.rglob)  # type: ignore
        # pathlib.Path.walk = _wrap_filename(pathlib.Path.walk)  # type: ignore
        # pathlib.Path.isPath =
        # pathlib.Path.exists =
        # pathlib.Path.is_file =
        # pathlib.Path.is_dir =
        # pathlib.Path.is_symlink =
        #
        # gzip.open = _wrap_filename(gzip.open)
        # configparser.ConfigParser.read = _wrap_filename(configparser.ConfigParser.read)
        #
        # import fileinput
        # fileinput.input = _wrap_filename(fileinput.input)
        #
        # import shutil
        # shutil.copyfileobj = _wrap_filename(shutil.copyfileobj)
        # shutil.copyfile = _wrap_filename(shutil.copyfile)
        # shutil.copymode = _wrap_filename(shutil.copymode)
        # shutil.copystat = _wrap_filename(shutil.copystat)
        # shutil.copy = _wrap_filename(shutil.copy)
        # shutil.copy2 = _wrap_filename(shutil.copy2)
        # shutil.copytree = _wrap_filename(shutil.copytree)
        # shutil.rmtree = _wrap_filename(shutil.rmtree)
        # shutil.move = _wrap_filename(shutil.move)
        # shutil.disk_usage = _wrap_filename(shutil.disk_usage)
        # shutil.chown = _wrap_filename(shutil.chown)
        # shutil.which = _wrap_filename(shutil.which)

        logger.error("Guard_filed activated. Standard socket.socket has been replaced.")
    else:
        logger.error("Guard_files was already activated.")

