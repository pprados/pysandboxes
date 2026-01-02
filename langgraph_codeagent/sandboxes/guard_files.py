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
        if arg.startswith("--bind="):
            value = arg[len("--bind="):]
            try:
                src, dest = value.split(",", 1)
                rules.append(ParserRule("bind", dest, src))
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


# Helper to resolve symlinks and apply rules
def _apply_rules(path: str) -> Optional[str]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    real_path = os.path.realpath(path)
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
    fake_path = os.path.realpath(path)
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


def _wrap_open(func: Callable[..., typing.IO]) -> Callable[..., typing.IO]:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike], *args, **kwargs):
        remapped = _apply_rules(os.fspath(file))
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return func(remapped, *args, **kwargs)

    return wrapper


def _wrap_listdir(func: Callable[..., List[str]]) -> Callable[..., List[str]]:
    @functools.wraps(func)
    def wrapper(path: Union[str, bytes, os.PathLike] = '.') -> List[str]:
        if new_path := _apply_rules(path):
            entries = func(new_path)
            filtered: List[str] = []
            for entry in entries:
                full_path = os.path.join(path, entry)
                if _apply_rules(full_path) is not None:
                    filtered.append(entry)
            return filtered
        else:
            raise FileNotFoundError(f"Access to '{path}' is ignored by rule")

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
        self.real_directory = _apply_rules(directory)
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


from pathlib import Path as _Path
from pathlib import Path as _Path
_Path_glob = _Path.glob

def _wrap_pathlib_glob(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self, glob: str) -> Iterator:
        if new_path := _apply_rules(self):
            return [str(_apply_inverse_rules(p)) for p in
                     _Path_glob(_Path(new_path), glob) if _apply_inverse_rules(p) is not None]
        else:
            raise FileNotFoundError(f"Access to '{self}' is ignored by rule")

    return wrapper


if "PYTEST_RUN_CONFIG" in os.environ:
    _remember={
        "builtins.open":builtins.open,
        "io.open":io.open,
        "os.open":os.open,
        "os.listdir":os.listdir,
        "os.scandir":os.scandir,
        "pathlib.Path.glob":_Path.glob
    }

    def deactivate_guard_files():
        builtins.open = _remember["builtins.open"]
        io.open = _remember["io.open"]
        os.open = _remember["os.open"]
        os.listdir = _remember["os.listdir"]
        os.scandir = _remember["os.scandir"]
        _Path.glob = _remember["pathlib.Path.glob"]
        global _rules
        _rules = []

def activate_guard_files(rules: List[str]) -> None:
    """
    Initializes the file access filter with the given rule list.
    Overrides built-in open and os.listdir functions.
    """
    # TODO: double invocation ?
    global _rules
    install_wrapper = not _rules
    _rules = _parse_rule(rules)

    if install_wrapper:
        builtins.open = _wrap_open(builtins.open)  # type: ignore

        import io
        io.open = _wrap_open(io.open)  # type: ignore
        # FIXME io.open_code = _wrap_open(io.open_code)  # type: ignore
        # io.FileIO = _wrap_open(io.FileIO)  # type: ignore

        import os
        os.open = _wrap_open(os.open)  # type: ignore
        os.listdir = _wrap_listdir(os.listdir)
        os.scandir = _wrap_scandir(os.scandir)
        # os.stat(path)
        # os.readlink(path)
        # os.symlink(src, dst)
        # os.rename(src, dst)
        # os.remove(path), os.unlink(path)
        # os.mkdir(path), os.makedirs(path)

        import pathlib
        # OK pathlib.Path.open = _wrap_open(pathlib.Path.open)  # type: ignore
        # OK pathlib.Path.read_text = _wrap_open(pathlib.Path.open)  # type: ignore
        # OK pathlib.Path.read_bytes = _wrap_open(pathlib.Path.open)  # type: ignore
        # OK pathlib.Path.write_text = _wrap_open(pathlib.Path.open)  # type: ignore
        # OK pathlib.Path.write_bytes = _wrap_open(pathlib.Path.open)  # type: ignore
        # OK pathlib.Path.iterdir = _wrap_open(pathlib.Path.open)  # type: ignore
        pathlib.Path.glob = _wrap_pathlib_glob(pathlib.Path.glob)  # type: ignore
        # pathlib.Path.rglob = _wrap_open(pathlib.Path.open)  # type: ignore
        # pathlib.Path.walk = _wrap_open(pathlib.Path.open)  # type: ignore
        # pathlib.Path.isPath =
        # pathlib.Path.exists =
        # pathlib.Path.is_file =
        # pathlib.Path.is_dir =
        # pathlib.Path.is_symlink =
        #
        # gzip.open = _wrap_open(gzip.open)
        # configparser.ConfigParser.read = _wrap_open(configparser.ConfigParser.readà)
        # import fileinput
        # fileinput.input = _wrap_open(fileinput.input)
        # import shutil
        # shutil.copyfileobj = _wrap_open(shutil.copyfileobj)
        # shutil.copyfile = _wrap_open(shutil.copyfile)
        # shutil.copymode = _wrap_open(shutil.copymode)
        # shutil.copystat = _wrap_open(shutil.copystat)
        # shutil.copy = _wrap_open(shutil.copy)
        # shutil.copy2 = _wrap_open(shutil.copy2)
        # shutil.copytree = _wrap_open(shutil.copytree)
        # shutil.rmtree = _wrap_open(shutil.rmtree)
        # shutil.move = _wrap_open(shutil.move)
        # shutil.disk_usage = _wrap_open(shutil.disk_usage)
        # shutil.chown = _wrap_open(shutil.chown)
        # shutil.which = _wrap_open(shutil.which)

        # os.path.abspath(path)
        # os.path.exists(path)
        # os.path.islink(path)
        # os.path.isdir(path)
        # os.path.isfile(path)
        # os.path.samefile(path1, path2)
        # os.path.realpath(path)
        # os.path.expanduser(path) → transforme ~ en /home/...
        # os.path.normpath(path)
        logger.error("Guard_filed activated. Standard socket.socket has been replaced.")
    else:
        logger.error("Guard_files was already activated.")

