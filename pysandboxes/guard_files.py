from os import scandir as _scandir

import builtins
import fnmatch
import functools
import inspect
import io
import logging
import os
import sys
import typing
import pathlib
from pathlib import Path as _Path
from types import TracebackType
from typing import Iterator
from typing import List, Callable, Optional, Union

from unit_tests import save_default_values, restore_default_values

_Path_glob = _Path.glob
_Path_rglob = _Path.rglob

logger = logging.getLogger(__name__)

# TODO: injecter les mappings dans les filtres de répertoires si c'est présent ? n'accepte pas mapping phantome ?

_white_list = [
    '<frozen posixpath>',
    '<frozen genericpath>',
    # FIXME "pathlib/_local.py",
]


# Internal representation of a rule
class BindRule:
    def __init__(self,
                 source: str,
                 dest: Optional[str] = None,
                 write: bool = True):
        self.source = source
        self.dest = dest
        self.write = write


class IgnoreRule:
    def __init__(self, pattern: str):
        self.source = pattern


Files_Rules=Union[BindRule, IgnoreRule]
# Internal state for the file filter
_rules: List[Files_Rules] = []

_os_path_realpath = os.path.realpath
_os_path_abspath = os.path.abspath


def parse_rules(arguments: List[str]) -> typing.Tuple[List[Files_Rules],List[str]]:
    """
    Parses rule strings into internal ParserRule objects.
    Supports --bind=src,dest and --ignore=glob_pattern.
    """
    rules: List[Files_Rules] = []
    ignore_rules: List[str] = []
    for line in arguments:
        if line.startswith("--bind="):
            value = line[len("--bind="):]
            try:
                src, dest = value.split(",", 1)
                rules.append(BindRule( src, dest, write=True))
            except ValueError:
                raise ValueError(f"Invalid bind rule: {line}")
        elif line.startswith("--ro-bind="):  # TODO: --ro-bind
            value = line[len("--ro-bind="):]
            try:
                src, dest = value.split(",", 1)
                rules.append(BindRule(src, dest, write=False))
            except ValueError:
                raise ValueError(f"Invalid bind rule: {line}")
        elif line.startswith("--ignore="):
            pattern = line[len("--ignore="):]
            rules.append(IgnoreRule(pattern))
        else:
            ignore_rules.append(line)
    return rules,ignore_rules


# Helper to resolve symlinks and apply rules
def _apply_src_to_dest_rules(path: str, accept_src: bool = False) -> Optional[str]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    real_path = _os_path_abspath(os.path.normpath(path))
    original_path = path

    for rule in _rules:
        if isinstance(rule, BindRule):
            if real_path.startswith(rule.source):
                if not accept_src and real_path == rule.source:  # and real_path.startswith(rule.dest):
                    return None
                relative = os.path.relpath(real_path, rule.source)
                if relative != ".":
                    new_path = os.path.join(rule.dest, relative)
                else:
                    new_path = rule.dest
                return new_path
        elif isinstance(rule, IgnoreRule):
            if fnmatch.fnmatch(original_path, rule.source) or fnmatch.fnmatch(
                    real_path, rule.source):
                return None
    return path


# Helper to resolve symlinks and apply rules
def _apply_dest_to_src_rules(path: str,
                             *,
                             write: bool,
                             accept_source: bool = False,
                             ) -> Optional[str]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    fake_path = _os_path_abspath(path)
    original_path = path

    for rule in _rules:
        if isinstance(rule, BindRule):
            if fake_path.startswith(rule.source):
                if not accept_source:
                    return None
            if fake_path.startswith(rule.dest):
                if not rule.write and write:
                    raise PermissionError(f"Cannot write to {rule.dest}")  # FIXME: msg
                # FIXME: a supprimer ?
                # if accept_source:
                #     return original_path
                relative = os.path.relpath(fake_path, rule.dest)
                new_path = os.path.join(rule.source, relative)
                return new_path
        elif isinstance(rule, IgnoreRule):
            if fnmatch.fnmatch(original_path, rule.source) or fnmatch.fnmatch(
                    fake_path, rule.source):
                return None
    return path


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


# %% Generic wrapper
def _wrap_filename(func: Callable, *, write: bool) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike, int], *args, **kwargs):
        # Detect call from posixpath
        if _special_caller():
            return func(file, *args, **kwargs)
        if isinstance(file, int):
            return func(file, *args, **kwargs)
        if isinstance(file, _DirEntry):
            file = file.path
        remapped = _apply_dest_to_src_rules(os.fspath(file), write=write)
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
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
        remapped_src = _apply_dest_to_src_rules(os.fspath(src), write=in_write)
        remapped_dest = _apply_dest_to_src_rules(os.fspath(dest), write=out_write)
        if remapped_src is None:
            raise FileNotFoundError(f"Access to '{src}' is ignored by rule")
        return func(str(remapped_src), str(remapped_dest), *args, **kwargs)

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
        need_to_write = (flags & os.O_WRONLY) or (flags & os.O_RDWR) or (
                flags & os.O_APPEND)
        remapped = _apply_dest_to_src_rules(os.fspath(file), write=need_to_write != 0)
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return func(remapped, flags, *args, **kwargs)

    return wrapper


def _wrap_os_getcwd(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Detect call from posixpath
        file = func(*args, **kwargs)
        remapped = _apply_src_to_dest_rules(os.fspath(file), accept_src=True)
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        if remapped.endswith(os.path.sep + "."):
            remapped = remapped[:-2]
        return str(remapped)

    return wrapper


def _wrap_os_listdir(func: Callable[..., List[str]]) -> Callable[..., List[str]]:
    @functools.wraps(func)
    def wrapper(path: Union[str, bytes, os.PathLike] = '.') -> List[str]:
        if new_path := _apply_dest_to_src_rules(path, write=False):
            if _special_caller():  # FIXME: a garder ?
                return func(new_path)
            entries = func(new_path)
            filtered: List[str] = []
            for entry in entries:
                full_path = os.path.join(path, entry)
                if _apply_dest_to_src_rules(full_path, write=False,
                                            accept_source=False) is not None:
                    filtered.append(entry)
            return filtered
        else:
            return []

    return wrapper


def _wrap_os_readlink(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike], *args, **kwargs):
        remapped_first = _apply_dest_to_src_rules(os.fspath(file), write=False)
        remapped = func(remapped_first, *args, **kwargs)
        if not remapped.startswith(os.path.sep):
            remapped = os.path.dirname(remapped_first) + "/" + remapped
        remapped = _apply_src_to_dest_rules(remapped)
        if not remapped:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return remapped

    return wrapper


class _DirEntry:
    def __init__(self,
                 target: typing.Any,
                 path: str) -> None:
        self._target = target
        self.path = path

    def __getattr__(self, name: str) -> typing.Any:
        print("_DirEntry.__get")
        # Called only if attribute not found the usual way
        if name == "path":
            return super().__getattr__(name)
        return getattr(self._target, name)

    def __setattr__(self, name: str, value: typing.Any) -> None:
        print("_DirEntry.__set")
        if name in ("_target", "path"):
            # Assign _target to self, not to target
            super().__setattr__(name, value)
        else:
            setattr(self._target, name, value)


class _ScanDirContextManager:
    """
    A context manager that wraps os.scandir and implements the context manager protocol.
    """

    def close(self):
        if self.scanner:
            self.scanner.close()

    def __init__(self, directory: str):
        self.directory = directory
        self.real_directory = _apply_dest_to_src_rules(directory, write=False)
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

        if not self.real_directory:
            raise StopIteration

        while True:
            try:
                while True:
                    entry = next(self.scanner)
                    dest_path = _apply_src_to_dest_rules(entry.path, accept_src=False)
                    if dest_path is not None:
                        _entry = _DirEntry(entry, dest_path)
                        return _entry
            except StopIteration:
                raise
            except Exception as e:
                print(f"Error iterating over {self.directory}: {e}")
                raise StopIteration


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
        remapped = _apply_dest_to_src_rules(os.fspath(file), write=False)
        file = func(remapped, *args, **kwargs)
        remapped = _apply_src_to_dest_rules(os.fspath(file))
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
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
        remapped = _apply_dest_to_src_rules(os.fspath(file), write=need_to_write)
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return func(remapped, mode, *args, **kwargs)

    return wrapper


# %% pathlib wrapper
def _wrap_pathlib(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike], *args, **kwargs):
        remapped = _apply_dest_to_src_rules(os.fspath(file), write=False)
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return func(pathlib.Path(remapped), *args, **kwargs)

    return wrapper


def _wrap_pathlib_glob(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self, glob: str, *args, **kwargs) -> Iterator:
        if new_path := _apply_dest_to_src_rules(self, write=False):
            return (pathlib.Path(_apply_src_to_dest_rules(p)) for p in
                    func(_Path(new_path), glob, *args, **kwargs)
                    if _apply_src_to_dest_rules(p) is not None)
        else:
            raise FileNotFoundError(f"Access to '{self}' is ignored by rule")

    return wrapper


# %%
if "PYTEST_RUN_CONFIG" in os.environ:
    
    _key_to_remember = {
        "builtins.open",
        # -----------------
        "os.chdir",
        "os.getcwd",
        "os.getcwdb",
        "os.open",
        "os.access",
        "os.chmod",
        "os.chroot",
        "os.link",
        "os.listdir",
        "os.mkdir",
        "os.readlink",
        "os.remove",
        "os.rename",
        "os.replace",
        "os.rmdir",
        "os.scandir",
        "os.stat",
        "os.lstat",
        "os.symlink",
        "os.truncate",
        "os.unlink",
        "os.utime",
        # -----------------
        "os.listxattr",
        "os.removexattr",
        "os.setxattr",
        "os.getxattr",
        "os.chflags",
        "os.lchflags",
        "os.lchmod",
        "os.chown",
        "os.lchown",
        # -----------------
        "io.open",
        "io.open_code",
        # -----------------
        "os.path.exists",
        "os.path.lexists",
        "os.path.getatime",
        "os.path.getmtime",
        "os.path.getctime",
        "os.path.getsize",
        "os.path.isfile",
        "os.path.isdir",
        "os.path.islink",
        "os.path.realpath",
        "os.path.samefile",
        # -----------------
        "pathlib.Path.glob",  # TODO: ajouter reste
    }
    _memory=dict()
    save_default_values(_memory,
                        _key_to_remember,
                        sys.modules[__name__],
                        )

    def _deactivate_guard_files():
        restore_default_values(_memory,
                               sys.modules[__name__])
        global _rules
        _rules = []

def activate_guard_files(rules: List[str]) -> None:
    """
    Initializes the file access filter with the given rule list.
    Overrides built-in open and os.listdir functions.
    """
    if not rules:
        return
    global _rules
    install_wrapper = not _rules
    _rules = rules

    if install_wrapper:
        builtins.open = _wrap_filename(builtins.open, write=True)

        # %% low level access
        import os
        os.chdir = _wrap_filename(os.chdir, write=False)
        # ALLOW os.fchdir
        os.getcwd = _wrap_os_getcwd(os.getcwd)
        os.getcwdb = _wrap_os_getcwd(os.getcwdb)
        # ALLOW os.fdopen
        # ALLOW os.tmpfile
        os.open = _wrap_os_open(os.open)
        os.access = _wrap_filename(os.access, write=False)
        if sys.platform != "win32" and sys.platform != "linux":
            os.chflags = _wrap_filename(os.chflags, write=True)
            os.lchflags = _wrap_filename(os.lchflags, write=True)
            os.lchmod = _wrap_filename(os.lchmod, write=True)
        os.chmod = _wrap_filename(os.chmod, write=True)
        if sys.platform != "win32":
            os.chown = _wrap_filename(os.chown, write=True)
            os.lchown = _wrap_filename(os.lchown, write=True)
        os.chroot = _wrap_filename(os.chroot, write=False)
        os.link = _wrap_two_filenames(os.link)  # TODO VERIF id = int
        os.listdir = _wrap_os_listdir(os.listdir)
        os.mkdir = _wrap_filename(os.mkdir, write=True)
        # DENY os.mkfifo
        # DENY os.mknod
        os.readlink = _wrap_os_readlink(os.readlink)
        os.remove = _wrap_filename(os.remove, write=True)
        # ALLOW os.removedirs= _wrap_filename(os.removedirs)
        os.rename = _wrap_two_filenames(os.rename, in_write=True, out_write=True)
        # ALLOW os.renames = _wrap_two_filenames(os.renames)
        os.replace = _wrap_two_filenames(os.replace, in_write=True, out_write=True)
        os.rmdir = _wrap_filename(os.rmdir, write=True)
        os.scandir = _wrap_os_scandir(os.scandir)
        os.stat = _wrap_filename(os.stat, write=False)
        # ALLOW os.statvfs = _wrap_filename(os.statvfs)
        os.lstat = _wrap_filename(os.lstat, write=False)
        # ALLOW os.stat_float_times
        os.symlink = _wrap_two_filenames(os.symlink)
        os.truncate = _wrap_filename(os.truncate, write=True)
        os.unlink = _wrap_filename(os.unlink, write=True)
        os.utime = _wrap_filename(os.utime, write=True)
        # ALLOW os.walk = _wrap_walk(os.walk)

        # Posix
        os.listxattr = _wrap_filename(os.listxattr, write=False)
        os.removexattr = _wrap_filename(os.removexattr, write=True)
        os.setxattr = _wrap_filename(os.setxattr, write=True)
        os.getxattr = _wrap_filename(os.getxattr, write=False)
        # TODO: revoir toutes les fonctions
        # DENY os.execv
        # DENY os.execve
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
        import io
        io.open = _wrap_io_open(io.open)
        io.open_code = _wrap_io_open(io.open_code)

        # %%
        # ALLOW os.path.abspath
        # ALLOW os.path.basename
        # ALLOW os.path.dirname
        os.path.exists = _wrap_filename(os.path.exists, write=False)
        os.path.lexists = _wrap_filename(os.path.lexists, write=False)
        # ALLOW os.path.expanduser
        # ALLOW os.path.expandvars
        os.path.getatime = _wrap_filename(os.path.getatime, write=False)
        os.path.getmtime = _wrap_filename(os.path.getmtime, write=False)
        os.path.getctime = _wrap_filename(os.path.getctime, write=False)
        os.path.getsize = _wrap_filename(os.path.getsize, write=False)
        # ALLOW os.path.isabs
        os.path.isfile = _wrap_filename(os.path.isfile, write=False)
        os.path.isdir = _wrap_filename(os.path.isdir, write=False)
        os.path.islink = _wrap_filename(os.path.islink, write=False)
        # ALLOW os.path.ismount
        # ALLOW os.path.join
        # ALLOW os.path.normcase
        # ALLOW os.path.normpath
        os.path.realpath = _wrap_os_path_realpath(os.path.realpath)
        # ALLOW os.path.relpath
        os.path.samefile = _wrap_two_filenames(os.path.samefile, out_write=False)
        # ALLOW os.path.expanduser
        # ALLOW os.path.walk (obsolette)

        # %%
        import pathlib
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
        # ALLOW pathlib.Path.open = _wrap_filename(pathlib.Path.open)
        # ALLOW pathlib.Path.read_bytes = _wrap_filename(pathlib.Path.read_bytes)
        # ALLOW pathlib.Path.read_text = _wrap_pathlib(pathlib.Path.read_text)
        # ALLOW pathlib.Path.write_bytes = _wrap_filename(pathlib.Path.write_bytes)
        # ALLOW pathlib.Path.write_text = _wrap_pathlib(pathlib.Path.write_text)
        # ALLOW pathlib.Path.iterdir = _wrap_pathlib_iterdir(pathlib.Path.iterdir)
        pathlib.Path.glob = _wrap_pathlib_glob(pathlib.Path.glob)
        # ALLOW pathlib.Path.rglob = _wrap_pathlib_glob(pathlib.Path.rglob)
        # pathlib.Path.walk = _wrap_filename(pathlib.Path.walk)
        # ALLOW pathlib.Path.relative_to
        # ALLOW pathlib.Path.is_relative_to
        # ALLOW pathlib.Path.is_absolute
        # ALLOW pathlib.Path.is_reserved
        # pathlib.Path.match
        # %%
        # ALLOW gzip.open = _wrap_filename(gzip.open)
        # %%
        # import fileinput
        # ALLOW fileinput.input = _wrap_filename(fileinput.input)
        # %%
        # import shutil
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

        logger.warning(
            "Guard_files activated.")
    else:
        logger.info("Guard_files was already activated.")
