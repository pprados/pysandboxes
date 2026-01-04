import builtins
import fnmatch
import functools
import io
import logging
import os
import sys
import typing
from types import TracebackType
from typing import Iterator
from typing import List, Callable, Optional, Union

logger = logging.getLogger(__name__)

# TODO: injecter les mappings dans les filtres de répertoires si c'est présent ? n'accepte pas mapping phantome ?

_white_list = [
    '<frozen posixpath>',
    '<frozen genericpath>',
    # FIXME "pathlib/_local.py",
]


# Internal representation of a rule
class ParserRule:
    def __init__(self, rule_type: str, pattern: str, replacement: Optional[str] = None):
        self.rule_type = rule_type  # 'bind' or 'ignore'
        self.source = pattern
        self.dest = replacement


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

_os_path_realpath = os.path.realpath
_os_path_abspath = os.path.abspath


# Helper to resolve symlinks and apply rules
def _apply_src_to_dest_rules(path: str, accept_src:bool=False) -> Optional[str]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    real_path = _os_path_abspath(os.path.normpath(path))
    original_path = path

    for rule in _rules:
        if rule.rule_type == "bind":
            if real_path.startswith(rule.source):
                if not accept_src and real_path == rule.source:  # and real_path.startswith(rule.dest):
                    return None
                relative = os.path.relpath(real_path, rule.source)
                if relative != ".":
                    new_path = os.path.join(rule.dest, relative)
                else:
                    new_path = rule.dest
                return new_path
        elif rule.rule_type == "ignore":
            if fnmatch.fnmatch(original_path, rule.source) or fnmatch.fnmatch(
                    real_path, rule.source):
                return None
    return path


# Helper to resolve symlinks and apply rules
def _apply_dest_to_src_rules(path: str, accept_source:bool=False) -> Optional[str]:
    """
    Applies the rules to a file path.
    Returns None if the file should be ignored.
    Otherwise, returns the potentially remapped path.
    """
    fake_path = _os_path_abspath(path)
    original_path = path

    for rule in _rules:
        if rule.rule_type == "bind":
            if fake_path.startswith(rule.source):
                if not accept_source:
                    return None
            if fake_path.startswith(rule.dest):
                if accept_source:
                    return original_path
                relative = os.path.relpath(fake_path, rule.dest)
                new_path = os.path.join(rule.source, relative)
                return new_path
        elif rule.rule_type == "ignore":
            if fnmatch.fnmatch(original_path, rule.source) or fnmatch.fnmatch(
                    fake_path, rule.source):
                return None
    return path


import inspect


def _wrap_filename(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(file: Union[str, bytes, os.PathLike, int], *args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename = None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(file, *args, **kwargs)
        print(f"wrapper {filename=}")  # FIXME
        if isinstance(file, int):
            return func(file, *args, **kwargs)
        if isinstance(file,_DirEntry):
            file=file.path
        remapped = _apply_dest_to_src_rules(os.fspath(file))
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return func(remapped, *args, **kwargs)

    return wrapper

def _wrap_two_filenames(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(src: Union[str, bytes, os.PathLike],
                dest: Union[str, bytes, os.PathLike],
                *args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename = None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(src, dest, *args, **kwargs)
        if isinstance(src,_DirEntry):
            src=src.path
        if isinstance(dest,_DirEntry):
            dest=dest.path
        remapped_src = _apply_dest_to_src_rules(os.fspath(src))
        remapped_dest = _apply_dest_to_src_rules(os.fspath(dest))
        if remapped_src is None:
            raise FileNotFoundError(f"Access to '{src}' is ignored by rule")
        return func(str(remapped_src), str(remapped_dest), *args, **kwargs)

    return wrapper


def _wrap_os_getcwd(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Detect call from posixpath
        frame = sys._getframe(1)
        filename = None
        if inspect.isframe(frame):
            code = frame.f_code
            filename = code.co_filename
        for wl in _white_list:
            if filename.endswith(wl):
                return func(*args, **kwargs)
        file = func(*args, **kwargs)
        remapped = _apply_src_to_dest_rules(os.fspath(file),accept_src=True)
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        if remapped.endswith(os.path.sep + "."):
            remapped = remapped[:-2]
        return str(remapped)

    return wrapper


def _wrap_realpath(func: Callable) -> Callable:
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
        remapped = _apply_dest_to_src_rules(os.fspath(file))
        file = func(remapped, *args, **kwargs)
        remapped = _apply_src_to_dest_rules(os.fspath(file))
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return remapped

    return wrapper


def _wrap_os_listdir(func: Callable[..., List[str]]) -> Callable[..., List[str]]:
    @functools.wraps(func)
    def wrapper(path: Union[str, bytes, os.PathLike] = '.') -> List[str]:
        if new_path := _apply_dest_to_src_rules(path):
            entries = func(new_path)
            filtered: List[str] = []
            for entry in entries:
                full_path = os.path.join(path, entry)
                if _apply_dest_to_src_rules(full_path) is not None:
                    filtered.append(entry)
            return filtered
        else:
            return []

    return wrapper



def _wrap_os_readlink(func: Callable) -> Callable:
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
                return func(file, *args, **kwargs)
        remapped_first = _apply_dest_to_src_rules(os.fspath(file))
        remapped = func(remapped_first, *args, **kwargs)
        if not remapped.startswith(os.path.sep):
            remapped = os.path.dirname(remapped_first) + "/" + remapped
        remapped = _apply_src_to_dest_rules(remapped)
        if not remapped:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return remapped

    return wrapper

# def _wrap_walk(func: Callable) -> Callable:
#     @functools.wraps(func)
#     def wrapper(file: Union[str, bytes, os.PathLike, int], *args, **kwargs):
#         # Detect call from posixpath
#         frame = sys._getframe(1)
#         filename = None
#         if inspect.isframe(frame):
#             code = frame.f_code
#             filename = code.co_filename
#         for wl in _white_list:
#             if filename.endswith(wl):
#                 return func(file, *args, **kwargs)
#         print(f"wrapper {filename=}")  # FIXME
#         if isinstance(file, int):
#             return func(file, *args, **kwargs)
#         remapped = _apply_dest_to_src_rules(os.fspath(file))
#         if remapped is None:
#             raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
#         not_showed=[]
#         for (rep,dirs,files) in func(remapped, *args, **kwargs):
#             inv_rep=_apply_dest_to_src_rules(rep)
#             # Change subdir with rules
#             new_dirs=[]
#             for d in dirs:
#                 new_d=_apply_src_to_dest_rules(rep+os.sep+d)
#                 if new_d is None:
#                     continue
#                 new_dir=os.path.split(new_d)[1]
#                 if new_dir not in new_dirs:
#                     new_dirs.append(new_dir)
#             if inv_rep != rep:
#                 rep=inv_rep
#             yield (rep,new_dirs,files)
#
#     return wrapper

# %%
from os import scandir as _scandir


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
        self.real_directory = _apply_dest_to_src_rules(directory)
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
                        _entry = _DirEntry(entry,dest_path)
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
        if isinstance(path,int):
            return func(path)
        return _ScanDirContextManager(path)

    return wrapper


from pathlib import Path
from pathlib import Path as _Path

_Path_glob = _Path.glob
_Path_rglob = _Path.rglob


def _wrap_pathlib(func: Callable) -> Callable:
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
                return func(file, *args, **kwargs)
        remapped = _apply_dest_to_src_rules(os.fspath(file))
        if remapped is None:
            raise FileNotFoundError(f"Access to '{file}' is ignored by rule")
        return func(Path(remapped), *args, **kwargs)

    return wrapper


def _wrap_pathlib_glob(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self, glob: str, *args, **kwargs) -> Iterator:
        if new_path := _apply_dest_to_src_rules(self):
            return (Path(_apply_src_to_dest_rules(p)) for p in
                    func(_Path(new_path), glob, *args, **kwargs)
                    if _apply_src_to_dest_rules(p) is not None)
        else:
            raise FileNotFoundError(f"Access to '{self}' is ignored by rule")

    return wrapper


if "PYTEST_RUN_CONFIG" in os.environ:
    _remember = {
        "builtins.open": builtins.open,
        # -----------------
        "io.open": io.open,
        # -----------------
        "os.chdir": os.chdir,
        "os.getcwd": os.getcwd,
        "os.getcwdb": os.getcwdb,
        "os.open": os.open,
        "os.access": os.access,
        "os.chroot": os.chroot,
        "os.chmod": os.chmod,
        "os.link": os.link,
        "os.listdir": os.listdir,
        "os.mkdir": os.mkdir,
        "os.readlink": os.readlink,
        "os.remove": os.remove,
        "os.rename": os.rename,
        "os.replace": os.replace,
        "os.rmdir": os.rmdir,
        "os.scandir": os.scandir,
        "os.stat": os.stat,
        "os.lstat": os.lstat,
        "os.symlink": os.symlink,
        "os.truncate": os.truncate,
        "os.unlink": os.unlink,
        "os.utime": os.utime,
        # -----------------
        "os.path.exists": os.path.exists,
        "os.path.lexists": os.path.lexists,
        "os.path.getatime": os.path.getatime,
        "os.path.getmtime": os.path.getmtime,
        "os.path.getctime": os.path.getctime,
        "os.path.getsize": os.path.getsize,
        "os.path.isfile": os.path.isfile,
        "os.path.isdir": os.path.isdir,
        "os.path.islink": os.path.islink,
        "os.path.realpath": os.path.realpath,
        "os.path.samefile": os.path.samefile,
        # -----------------
        "pathlib.Path.glob": _Path.glob,  # TODO: ajouter reste
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


    def _deactivate_guard_files():
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

        os.path.exists = _remember["os.path.exists"]
        os.path.lexists = _remember["os.path.lexists"]
        os.path.getatime = _remember["os.path.getatime"]
        os.path.getmtime = _remember["os.path.getmtime"]
        os.path.getctime = _remember["os.path.getctime"]
        os.path.getsize = _remember["os.path.getsize"]
        os.path.isfile = _remember["os.path.isfile"]
        os.path.isdir = _remember["os.path.isdir"]
        os.path.islink = _remember["os.path.islink"]
        os.path.realpath = _remember["os.path.realpath"]
        os.path.samefile = _remember["os.path.samefile"]

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
        builtins.open = _wrap_filename(builtins.open)

        import io
        io.open = _wrap_filename(io.open)
        io.open_code = _wrap_filename(io.open_code)

        # %%
        import os
        os.chdir = _wrap_filename(os.chdir)
        # ALLOW os.fchdir
        os.getcwd = _wrap_os_getcwd(os.getcwd)
        os.getcwdb = _wrap_os_getcwd(os.getcwdb)
        # ALLOW os.fdopen
        # ALLOW os.tmpfile
        os.open = _wrap_filename(os.open)
        os.access = _wrap_filename(os.access)
        if sys.platform != "win32" and sys.platform != "linux":
            os.chflags = _wrap_filename(os.chflags)
            os.lchflags = _wrap_filename(os.lchflags)
            os.lchmod = _wrap_filename(os.lchmod)
        os.chmod = _wrap_filename(os.chmod)
        if sys.platform != "win32":
            os.chown = _wrap_filename(os.chown)
            os.lchown = _wrap_filename(os.lchown)
        os.chroot = _wrap_filename(os.chroot)
        os.link = _wrap_two_filenames(os.link)  # TODO VERIF id = int
        os.listdir = _wrap_os_listdir(os.listdir)
        os.mkdir = _wrap_filename(os.mkdir)
        # DENY os.mkfifo
        # DENY os.mknod
        os.readlink = _wrap_os_readlink(os.readlink)
        os.remove = _wrap_filename(os.remove)
        # ALLOW os.removedirs= _wrap_filename(os.removedirs)
        os.rename = _wrap_two_filenames(os.rename)
        # ALLOW os.renames = _wrap_two_filenames(os.renames)
        os.replace = _wrap_two_filenames(os.replace)
        os.rmdir = _wrap_filename(os.rmdir)
        os.scandir = _wrap_os_scandir(os.scandir)
        os.stat = _wrap_filename(os.stat)
        # ALLOW os.statvfs = _wrap_filename(os.statvfs)
        os.lstat = _wrap_filename(os.lstat)
        # ALLOW os.stat_float_times
        os.symlink = _wrap_two_filenames(os.symlink)
        os.truncate = _wrap_filename(os.truncate)
        os.unlink = _wrap_filename(os.unlink)
        os.utime = _wrap_filename(os.utime)
        # ALLOW os.walk = _wrap_walk(os.walk)

        # Posix
        os.listxattr = _wrap_filename(os.listxattr)
        os.removexattr = _wrap_filename(os.removexattr)
        os.setxattr = _wrap_filename(os.setxattr)
        os.getxattr = _wrap_filename(os.getxattr)
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

        # %%
        # ALLOW os.path.abspath= _wrap_filename(os.path.abspath)
        # ALLOW os.path.basename
        # ALLOW os.path.dirname= _wrap_filename(os.path.dirname)
        os.path.exists = _wrap_filename(os.path.exists)
        os.path.lexists = _wrap_filename(os.path.lexists)
        # ALLOW os.path.expanduser
        # ALLOW os.path.expandvars
        os.path.getatime = _wrap_filename(os.path.getatime)
        os.path.getmtime = _wrap_filename(os.path.getmtime)
        os.path.getctime = _wrap_filename(os.path.getctime)
        os.path.getsize = _wrap_filename(os.path.getsize)
        # ALLOW os.path.isabs
        os.path.isfile = _wrap_filename(os.path.isfile)
        os.path.isdir = _wrap_filename(os.path.isdir)
        os.path.islink = _wrap_filename(os.path.islink)
        # ALLOW os.path.ismount= _wrap_filename(os.path.ismount)
        # ALLOW os.path.join
        # ALLOW os.path.normcase
        # ALLOW os.path.normpath
        os.path.realpath = _wrap_realpath(os.path.realpath)
        # ALLOW os.path.relpath
        os.path.samefile = _wrap_two_filenames(os.path.samefile)
        # ALLOW os.path.expanduser(path) → transforme ~ en /home/...
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
            "Guard_filed activated. Standard socket.socket has been replaced.")
    else:
        logger.info("Guard_files was already activated.")
