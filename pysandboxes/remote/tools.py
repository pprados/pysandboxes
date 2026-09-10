# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Utility functions for PySandboxes remote execution modules.

This module provides various utility functions used by the remote execution
components including package management, network configuration, logging setup,
and system-level operations for process management.

Key utilities:
- Package installation suggestions based on OS detection
- Network gateway information retrieval
- Process death signal management (pdeathsig)
- Serialization utilities for remote communication
"""

import base64
import datetime
import decimal
import errno as errno_mod
import io
import ipaddress
import logging
import os
import pickle
import pickletools
import platform
import re
import shutil
import signal
import subprocess
import sys  # Import the sys module to access system-specific parameters and functions
import textwrap
from ctypes import cdll
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from collections.abc import Callable
from typing import Any, cast

from ..e import RestrictedUnpicklingError, set_sandbox_denials

logger = logging.getLogger(__name__)

known_paths = [
    Path("/bin/"),
    Path("/usr/bin/"),
    Path("/usr/local/bin/"),
]


# Errno values a daemon's readiness ping must ride out. The listening
# socket can already be open while the server finishes initialising, so
# the accepted connection gets reset; aiohttp surfaces that as a
# ClientOSError, which derives from OSError. Anything outside this set
# (EMFILE, ENOMEM, EACCES) is a real fault and must not be swallowed by
# a retry loop, or it only shows up once the ping budget runs out.
_TRANSIENT_CONNECTION_ERRNOS = frozenset(
    {
        errno_mod.ECONNRESET,
        errno_mod.ECONNABORTED,
        errno_mod.EPIPE,
    }
)


def is_transient_connection_error(error: OSError) -> bool:
    """Whether a connection error is worth retrying during startup.

    Takes an OSError rather than aiohttp's ClientOSError so this module
    keeps no HTTP client import. An error carrying no errno is treated
    as a real fault: better to surface it than to retry blindly.
    """
    return error.errno in _TRANSIENT_CONNECTION_ERRNOS


def which_command(command: str) -> Path | None:
    """Find executable command in known system paths.

    Args:
        command: Command name to search for.

    Returns:
        Path to command executable or None if not found.
    """
    for path in known_paths:
        if (path / command).exists():
            return path / command
    full_path = shutil.which(command)
    if not full_path:
        return None
    return Path(full_path)


def unshare_user_namespace_available() -> bool:
    """Return True if unshare and slirp4netns exist and user namespaces are allowed.

    When user namespaces are disabled (e.g. in containers, Cursor, or kernel
    setting), unshare fails with 'Operation not permitted'. This avoids hanging
    or long timeouts in tests.
    """
    if not which_command("unshare") or not which_command("slirp4netns"):
        return False
    try:
        result = subprocess.run(
            ["unshare", "--user", "--map-root-user", "true"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def get_venv() -> str | None:
    """Get current virtual environment path.

    Returns:
        Path to virtual environment or None if not in venv.
    """
    if sys.prefix != sys.base_prefix:
        venv_path = sys.prefix
        return venv_path
    else:
        return os.environ.get("VIRTUAL_ENV")


def configure_logging_level(verbose_count: int) -> int:
    """Configure logging level based on verbose flag count.

    Args:
        verbose_count: Number of verbose flags:
                      - 0: ERROR
                      - 1: WARNING
                      - 2: INFO
                      - 3: DEBUG
                      - 4+: NOTSET

    Returns:
        Configured logging level constant.
    """
    if verbose_count == 0:
        log_level = logging.ERROR
    elif verbose_count == 1:
        log_level = logging.WARNING
    elif verbose_count == 2:
        log_level = logging.INFO
    elif verbose_count == 3:
        log_level = logging.DEBUG
    else:  # verbose_count >= 4
        log_level = logging.NOTSET

    logging.getLogger().setLevel(log_level)  # Root logger
    return log_level


def get_default_gateway_info() -> tuple[str, str] | None:
    """Get default network gateway information.

    netifaces is imported lazily: its C extension can segfault on some minimal
    VM/guest stacks; nothing in the daemon import path needs gateways at module load.

    Returns:
        Tuple of (gateway_ip, interface_name) or None if no gateway found.
    """
    import netifaces

    gws: dict[Any, Any] = netifaces.gateways()

    # Retrieve default IPv4 gateway
    try:
        if netifaces.AF_INET in gws["default"]:
            # The structure for default gateway
            # is (gateway_ip, interface_name, is_primary)
            ipv4_gateway_data = gws["default"][netifaces.AF_INET]
            return ipv4_gateway_data

        # Retrieve default IPv6 gateway
        if netifaces.AF_INET6 in gws["default"]:
            # The structure for default gateway
            # is (gateway_ip, interface_name, is_primary)
            ipv6_gateway_data = gws["default"][netifaces.AF_INET6]
            return ipv6_gateway_data
    except KeyError:
        # No default gateway found for the specified address family
        pass
    return None


def suggest_package_installation(package_name: str) -> str:
    """Suggest package installation command based on detected OS.

    Args:
        package_name: Name of the package to install.

    Returns:
        Installation command string for the detected OS/distribution.
    """
    system: str = sys.platform

    if system.startswith("linux"):
        # Try to identify the specific Linux distribution
        distro_info: dict[str, str] = {}
        try:
            # Read /etc/os-release for detailed distribution information
            with open("/etc/os-release", "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        key, value = line.split("=", 1)
                        distro_info[key] = value.strip('"')
        except FileNotFoundError:
            # Fallback for older systems that might use /etc/lsb-release
            try:
                with open("/etc/lsb-release", "r") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line:
                            key, value = line.split("=", 1)
                            distro_info[key] = value.strip('"')
            except FileNotFoundError:
                pass  # No specific distro info found

        distro_id: str = distro_info.get("ID", "").lower()  # Get the ID of the distribution

        if distro_id == "ubuntu" or distro_id == "debian":
            return f"sudo apt update && sudo apt install {package_name}"
        elif distro_id == "fedora":
            return f"sudo dnf install {package_name}"
        elif distro_id == "centos" or distro_id == "rhel":
            return f"sudo yum install {package_name}"
        elif distro_id == "arch":
            return f"sudo pacman -S {package_name}"
        else:
            # Fallback for unknown or other Linux distributions
            return textwrap.dedent(f"""
                You can try installing {package_name!r} using common package managers like:
                sudo apt update && sudo apt install {package_name}  (Debian/Ubuntu based systems)
                sudo yum install {package_name}          (CentOS/RHEL based systems)
                sudo dnf install {package_name}          (Fedora based systems)
                sudo pacman -S {package_name}            (Arch Linux based systems)
                Please refer to your distribution's documentation for the correct command.
                """).strip()  # noqa: E501  # noqa

    elif system == "darwin":
        # For macOS, suggest Homebrew
        return textwrap.dedent(f"""
            /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
            brew install {package_name}
            """).strip()  # noqa
    elif system == "win32":
        # For Windows, suggest Winget or Chocolatey
        return textwrap.dedent(f"""
            You can try installing {package_name!r} using:")
              winget install {package_name}            (Windows Package Manager)
              choco install {package_name}             (Chocolatey - if installed)
            You might need to install Winget or Chocolatey first if you don't have them.
            """).strip()
    else:
        # For other or unknown systems
        return textwrap.dedent(f"""
            Your operating system ({system}) is not explicitly supported.
            Please refer to the documentation for {package_name!r} to find installation instructions for your system.
            """).strip()  # noqa: E501


def return_level_parameter(log_level: int) -> str:
    """Convert logging level to verbose parameter string.

    Args:
        log_level: Logging level constant.

    Returns:
        Corresponding verbose parameter string (e.g., '-v', '-vv').
    """
    _map = {
        logging.WARN: "",
        logging.INFO: "-v",
        logging.DEBUG: "-vv",
        logging.NOTSET: "-vvv",
    }
    return _map.get(log_level, "-vvv")


# Constant from linux/prctl.h
PR_SET_PDEATHSIG = 1


def set_pdeathsig() -> None:
    """Set process death signal to receive SIGTERM when parent dies.

    Only works on POSIX systems with prctl support.
    """
    if os.name != "posix":
        logger.warning("set_pdeathsig() not supported on non-POSIX systems.")
        return
    try:
        libc = cdll.LoadLibrary("libc.so.6")
        result = libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
        if result != 0:
            logging.warning("prctl(PR_SET_PDEATHSIG, SIGTERM) failed with code %s", result)
    except OSError:
        logging.warning("prctl not available (not Linux or libc not found).")


# Bound here, at import, because `pickle.loads` is a guard_api target: resolving
# it as a module attribute at call time would hand the SSE transport the guarded
# wrapper, and the framework's own serialization would then be charged to the
# user's `python-api=` rules -- a profile that never mentions pickle would break
# its own result and exception path. Binding the name before any patch is posted
# captures the original, with no caller check to arrange one's way around.
#
# This does not make the transport safe: `from_b85` still unpickles a payload
# the sandboxed child produced. See wiki/audit-python-security.md.
_pickle_dumps = pickle.dumps
_pickle_loads = pickle.loads

# CPYTHON-COMPAT: pin the wire protocol to a constant, not pickle.HIGHEST_PROTOCOL.
# The two ends may run different interpreters (container backends), and the opcode
# allowlist below is defined for this protocol. Inert while HIGHEST_PROTOCOL == 5
# (CPython 3.11-3.14); revisit if a future version raises it to 6.
_PICKLE_PROTOCOL = 5


def to_b85(obj: Any) -> str:
    """Serialize object to base85-encoded string.

    Args:
        obj: Object to serialize.

    Returns:
        Base85-encoded serialized object string.
    """
    result = base64.b85encode(
        # serialization only
        _pickle_dumps(obj, protocol=_PICKLE_PROTOCOL)
    ).decode("ascii")
    # Round-trip check on locally built data
    assert _pickle_loads(base64.b85decode(result.encode("ascii"))) == obj
    return result


def from_b85(b85: str) -> Any:
    """Deserialize object from base85-encoded string.

    Args:
        b85: Base85-encoded string.

    Returns:
        Deserialized object.
    """
    # IPC transport; child->parent results are untrusted (open issue)
    return _pickle_loads(
        base64.b85decode(b85.encode("ascii")),
    )


# --- Restricted unpickler for the untrusted child->parent SSE channel --------
#
# `from_b85` above stays raw for the trusted parent->child direction (args and
# kwargs the parent sends the child). The two child->parent sites in
# base_sse_daemon.py go through
# `from_b85_restricted`, because the child produced that payload and the parent
# is trusted.

# CPYTHON-COMPAT: opcode alphabet enumerated by family for protocol 5
# (CPython 3.11-3.14). The corpus test in tests reasserts every opcode a
# representative sample emits stays in this set, so a CPython bump reddens CI
# instead of silently breaking the transport.
_ALLOWED_OPCODES = frozenset(
    {
        "PROTO",
        "FRAME",
        "STOP",
        "MEMOIZE",
        "BINPUT",
        "LONG_BINPUT",
        "BINGET",
        "LONG_BINGET",
        "NONE",
        "NEWTRUE",
        "NEWFALSE",
        "BININT",
        "BININT1",
        "BININT2",
        "LONG1",
        "LONG4",
        "BINFLOAT",
        "SHORT_BINUNICODE",
        "BINUNICODE",
        "BINUNICODE8",
        "SHORT_BINBYTES",
        "BINBYTES",
        "BINBYTES8",
        "BYTEARRAY8",
        "EMPTY_LIST",
        "APPEND",
        "APPENDS",
        "EMPTY_DICT",
        "SETITEM",
        "SETITEMS",
        "EMPTY_TUPLE",
        "TUPLE1",
        "TUPLE2",
        "TUPLE3",
        "TUPLE",
        "EMPTY_SET",
        "ADDITEMS",
        "FROZENSET",
        "MARK",
        "STACK_GLOBAL",
        "REDUCE",
        "BUILD",
        "NEWOBJ",
        "NEWOBJ_EX",
    }
)

# Anti-DoS budgets: generous guard-rails, not tight limits. A legitimate result
# may be large; these only bound the pathological shapes the predicate cannot
# see (memo bombs, opcode floods) that would expand in the parent's RAM.
_MAX_OPCODES = 5_000_000
_MAX_MEMO = 2_000_000
_MAX_MARK_DEPTH = 256

# The payload travels as one SSE line, and aiohttp caps a line at
# 8 * ClientSession(read_bufsize=...), i.e. 8 * 65536 = 512 KiB on the default.
# Measured end to end: a line of 524240 bytes crosses, 524242 raises
# aiohttp LineTooLong -- so the real ceiling is the HTTP reader, not this
# budget. It used to read 128 MiB, two orders of magnitude above what the
# transport can carry, which made it a number that described nothing.
#
# Derivation, in the direction the wire imposes:
#   line   <= 8 * read_bufsize                       = 524288
#   line    = b85(pickle) + SSE/JSON envelope + captured stdout/stderr
#   b85(n)  = ceil(n / 4) * 5                        = 1.25 * n
#   n      <= (524288 - envelope) / 1.25             = 419392 with no output
# 384 KiB encodes to 491520 bytes, leaving 32 KiB of the line for the envelope
# and for whatever the sandboxed function printed. Above that the reader would
# refuse the line before this prescan ever sees it.
#
# CPYTHON-COMPAT-ADJACENT: keyed to an aiohttp default, not to CPython. Raising
# read_bufsize on the ClientSession in base_sse_daemon.py is what would let this
# budget grow; a test pins the relation so a change on either side reddens CI.
_SSE_LINE_LIMIT = 8 * 65536
_B85_EXPANSION = 1.25
_MAX_BYTES = 384 * 1024

# Opcodes that consume one MARK, used to track MARK nesting depth.
_MARK_CONSUMERS = frozenset({"TUPLE", "SETITEMS", "APPENDS", "ADDITEMS", "FROZENSET"})

# Base data classes that reach find_class via STACK_GLOBAL (plain int/str/list/
# dict/... use direct opcodes and never hit find_class). Allowed on the
# exception channel, where an exception's state may carry one of these.
_BASE_DATA_CLASSES = frozenset(
    {
        datetime.datetime,
        datetime.date,
        datetime.time,
        datetime.timedelta,
        datetime.timezone,
        decimal.Decimal,
        complex,
    }
)

# CPYTHON-COMPAT: denylist keyed by every alias / C-twin that can appear as
# __module__ in the stream. `os.system` arrives as `posix.system` (Linux) or
# `nt.system` (Windows); `socket.socket` can arrive as `_socket.socket`. A
# denylist by import name would miss the proven gadget. Fail-open by nature: a
# module not listed here passes -- this is the "risky" layer the profile switch
# disables. The denylist is not exhaustive; an unlisted module passes.
_DENIED_MODULE_ROOTS = frozenset(
    {
        "posix",
        "nt",
        "os",
        "subprocess",
        "pty",
        "sys",
        "importlib",
        "runpy",
        "socket",
        "_socket",
        "_thread",
        "threading",
        "ctypes",
        "_ctypes",
        "mmap",
        "operator",
        "functools",
        "pdb",
        "platform",
        "webbrowser",
        "code",
        "codeop",
        "timeit",
    }
)
_DENIED_BUILTINS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "__build_class__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "vars",
        "breakpoint",
        "open",
        "input",
        "memoryview",
        "type",
    }
)


def _prescan(data: bytes) -> None:
    """Reject a pickle stream on opcode alphabet or size before any execution.

    `pickletools.genops` parses without executing (no `__reduce__` runs). This
    does NOT inventory `(module, name)`: under memo/BINGET indirection a
    stack-simulating scan diverges from the C unpickler, so names are left to
    `find_class`. This layer closes only what `find_class` cannot see -- opcodes
    that bypass it (EXT*, proto-0 GLOBAL/INST/OBJ) and size bombs.

    Args:
        data: The raw (base85-decoded) pickle bytes.

    Raises:
        RestrictedUnpicklingError: On a forbidden opcode, a budget overrun, or
            an unparsable stream.
    """
    if len(data) > _MAX_BYTES:
        raise RestrictedUnpicklingError(
            f"payload of {len(data)} bytes exceeds the {_MAX_BYTES}-byte transport budget; "
            "the SSE line that carries it would not fit the HTTP reader."
        )
    n_op = 0
    n_memo = 0
    mark_depth = 0
    try:
        for opcode, _arg, _pos in pickletools.genops(data):
            n_op += 1
            if n_op > _MAX_OPCODES:
                raise RestrictedUnpicklingError(f"stream exceeds the {_MAX_OPCODES}-opcode transport budget.")
            name = opcode.name
            if name not in _ALLOWED_OPCODES:
                raise RestrictedUnpicklingError(f"opcode {name!r} is not allowed on the sandbox transport.")
            if name == "MARK":
                mark_depth += 1
                if mark_depth > _MAX_MARK_DEPTH:
                    raise RestrictedUnpicklingError(f"stream exceeds the {_MAX_MARK_DEPTH}-deep MARK budget.")
            elif name in _MARK_CONSUMERS and mark_depth > 0:
                mark_depth -= 1
            elif name in ("MEMOIZE", "BINPUT", "LONG_BINPUT"):
                n_memo += 1
                if n_memo > _MAX_MEMO:
                    raise RestrictedUnpicklingError(f"stream exceeds the {_MAX_MEMO}-entry memo budget.")
    except RestrictedUnpicklingError:
        raise
    except Exception as exc:
        # A malformed or truncated stream makes genops raise: refuse, don't crash.
        raise RestrictedUnpicklingError(f"unparsable pickle stream: {exc}") from exc


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that resolves every global through an injected predicate."""

    def __init__(self, data: bytes, predicate: Callable[[str, str, Any], bool]) -> None:
        """Bind the stream and the per-site predicate.

        Args:
            data: The raw (base85-decoded) pickle bytes, already prescanned.
            predicate: `(module, name, resolved_obj) -> bool`; a false return
                refuses the global.
        """
        super().__init__(io.BytesIO(data))
        self._predicate = predicate

    def find_class(self, module: str, name: str) -> Any:
        """Resolve a global only if already loaded and accepted by the predicate.

        Args:
            module: The module name carried by the stream.
            name: The (possibly dotted) qualified name carried by the stream.

        Returns:
            The resolved class or callable.

        Raises:
            RestrictedUnpicklingError: If the module is not loaded, the name
                cannot be resolved, or the predicate refuses it.
        """
        # CPYTHON-COMPAT: never import from the stream -- only modules already
        # loaded in the trusted parent. `os`/`posix` are usually loaded, so this
        # does not block them; the predicate does.
        mod = sys.modules.get(module)
        if mod is None:
            # All module used by the server must be pre-loader in the client.
            raise RestrictedUnpicklingError(
                f"module {module!r} is not loaded in the client; the transport refuses to import it."
            )
        # CPYTHON-COMPAT: resolve the dotted qualname in-house (protocol >= 4
        # STACK_GLOBAL carries `Outer.Inner`). `pickle._getattribute` is private
        # and its signature/return have changed across versions.
        obj: Any = mod
        try:
            for part in name.split("."):
                obj = getattr(obj, part)
        except AttributeError as exc:
            raise RestrictedUnpicklingError(f"{module}.{name} could not be resolved on the transport.") from exc
        if not self._predicate(module, name, obj):
            raise RestrictedUnpicklingError(f"{module}.{name} is refused by the sandbox transport guard.")
        return obj


def _is_base_data_class(obj: Any) -> bool:
    """True for a base data class that legitimately reaches find_class."""
    return obj in _BASE_DATA_CLASSES


def exception_predicate(module: str, name: str, obj: Any) -> bool:
    """Accept an exception class, tblib's own types, or a base data class.

    Used on the exception channel. Keys on `Exception`, not `BaseException`,
    so `SystemExit`/`KeyboardInterrupt` stay out of the gadget set.
    """
    if isinstance(obj, type) and issubclass(obj, Exception):
        return True
    if module == "tblib" or module.startswith("tblib."):
        return True
    return _is_base_data_class(obj)


def result_predicate(module: str, name: str, obj: Any) -> bool:
    """Deny a known dangerous gadget; allow the rest (result channel).

    Fail-open by design: only the modules/builtins enumerated as dangerous are
    refused, so legitimate results (pathlib, uuid, numpy, app types) pass. This
    is the layer the profile switch disables.
    """
    root = module.split(".")[0]
    if root in _DENIED_MODULE_ROOTS:
        return False
    if module == "builtins" and name in _DENIED_BUILTINS:
        return False
    return True


def descriptor_predicate(module: str, name: str, obj: Any) -> bool:
    """Accept only tblib's own types (fallback exception channel).

    The fallback payload is built from `str` and `list[str]` plus the
    traceback. Those reach the unpickler through direct opcodes, never through
    `find_class`, so tblib is the only global a well-formed descriptor carries.
    """
    return module == "tblib" or module.startswith("tblib.")


def describe_exception(exception: BaseException, denials: list[str]) -> tuple[str, str, str, list[str]]:
    """Reduce an exception to primitives, for the fallback channel (child side).

    The rich form pickles the exception object, which drags its whole state
    along -- an `httpx.Request`, a `Path`, an application object. The guard on
    the parent refuses those, so the refusal itself would be lost. This form
    carries no object at all.

    Args:
        exception: The exception leaving the sandbox.
        denials: The sandbox denials recorded on it, as `sandbox_denials`
            returns them.

    Returns:
        `(module, qualname, message, denials)`, all primitives.
    """
    cls = type(exception)
    return (cls.__module__, cls.__qualname__, str(exception), list(denials))


def rebuild_from_descriptor(
    descriptor: tuple[str, str, str, list[str]],
    fallback_class: type[BaseException],
) -> BaseException:
    """Rebuild an exception from its primitives (parent side).

    Resolves the class the way `find_class` does -- from `sys.modules` only,
    never importing -- and instantiates it through `__new__`, since an
    exception's `__init__` signature is its own business and replaying it with
    one argument fails on any class that takes more. When the class cannot be
    resolved, or is not an `Exception` subclass, `fallback_class` stands in so
    the refusal still reaches the caller.

    Args:
        descriptor: What `describe_exception` produced.
        fallback_class: Exception class used when resolution fails.

    Returns:
        An exception of the original class when it could be resolved, else of
        `fallback_class`, carrying the message and the denials.
    """
    module, qualname, message, denials = descriptor
    cls: Any = sys.modules.get(module)
    try:
        for part in qualname.split("."):
            cls = getattr(cls, part)
    except (AttributeError, TypeError):
        cls = None
    # `Exception`, not `BaseException`, to match exception_predicate: the
    # fallback must not let the child forge a SystemExit or KeyboardInterrupt
    # that the rich form would have refused.
    if not (isinstance(cls, type) and issubclass(cls, Exception)):
        cls = fallback_class
        message = f"{module}.{qualname}: {message}"
    try:
        exception = cls.__new__(cls)
        exception.args = (message,)
    except Exception:
        # A class with a demanding __new__ (some OSError subclasses) or a
        # read-only args: the message still has to reach the caller.
        exception = fallback_class(f"{module}.{qualname}: {message}")
    if denials:
        set_sandbox_denials(exception, denials)
    return exception


def from_b85_restricted(
    b85: str,
    predicate: Callable[[str, str, Any], bool] | None,
) -> Any:
    """Deserialize an untrusted child->parent payload under transport guards.

    Always runs `_prescan` (opcode allowlist + budgets), which the profile
    switch never disables. When `predicate` is None the name-level guard is off
    (the result switch turned it off) and a standard load runs after the
    prescan; otherwise every global resolves only through `predicate`.

    Args:
        b85: Base85-encoded payload produced by the sandboxed child.
        predicate: `(module, name, obj) -> bool` gating each global, or None to
            run a standard load after the prescan.

    Returns:
        The deserialized object.

    Raises:
        RestrictedUnpicklingError: On a refused opcode, budget, or global.
    """
    data = base64.b85decode(b85.encode("ascii"))
    _prescan(data)
    if predicate is None:
        return _pickle_loads(data)
    return _RestrictedUnpickler(data, predicate).load()


def _get_default_interface_via_ip() -> str | None:
    """
    Retrieves the name of the default network interface on a Linux system
    by parsing the output of the 'ip route' command.

    The default interface is the one associated with the 'default' route
    (0.0.0.0/0) in the routing table.

    Returns:
        str | None: The name of the default interface (e.g., 'eth0', 'wlan0'),
                    or None if it cannot be determined.
    """
    try:
        # 1. Execute the 'ip route' command to get the routing table
        # We use a timeout to prevent the call from hanging indefinitely
        # check=True will raise CalledProcessError on non-zero exit codes
        result = subprocess.run(["ip", "route"], capture_output=True, text=True, check=True, timeout=5)
        output: str = result.stdout

        # 2. Search for the default route line
        # The line typically starts with 'default via <gateway_ip> dev <interface_name>'
        # Example: 'default via 192.168.1.1 dev eth0 proto dhcp src 192.168.1.100 metric 100'
        # We use a regex to capture the 'dev <interface_name>' part
        default_route_pattern: re.Pattern = re.compile(r"^default\s+.*dev\s+(\S+)", re.MULTILINE)

        match: re.Match[str] | None = default_route_pattern.search(output)

        if match:
            # Group 1 contains the interface name
            interface_name: str = match.group(1)
            return interface_name
        else:
            # Default route not found in the output
            return None

    except FileNotFoundError:
        # This occurs if the 'ip' command is not found on the system (highly unlikely on Ubuntu)
        logger.warning("Error: 'ip' command not found. Ensure iproute2 package is installed.")
        return None
    except subprocess.CalledProcessError as e:
        # This handles non-zero exit codes from the command
        logger.warning("Error executing 'ip route': %s", e.stderr.strip())
        return None
    except subprocess.TimeoutExpired:
        # This handles the command taking too long to execute
        logger.warning("Error: 'ip route' command timed out.")
        return None
    except Exception as e:
        # Catch any other unexpected errors
        logger.warning("An unexpected error occurred: %s", str(e))
        return None


def get_default_interface() -> str | None:
    """
    Retrieves the name of the default network interface by reading the
    /proc/net/route pseudo-file on Linux.

    Returns the interface name (str) or None if not found.
    """
    # The default route destination is represented by '00000000' in the file
    DEFAULT_DESTINATION: str = "00000000"

    try:
        # Open the file containing the routing table
        with open("/proc/net/route", "r") as f:
            # Read all lines
            content_lines: list[str] = f.readlines()

        # Iterate over lines, skipping the header (first line)
        for line in content_lines[1:]:
            # Split the line by tabs or spaces
            parts: list[str] = line.split()

            # parts[1] is the Destination column
            if len(parts) > 1 and parts[1] == DEFAULT_DESTINATION:
                # parts[0] is the Iface (Interface name) column
                interface_name: str = parts[0]
                return interface_name

    except FileNotFoundError:
        # If the system is not Linux or the file is missing
        logger.info("The file /proc/net/route not found.")
        return None

    return _get_default_interface_via_ip()


def get_bridge_interfaces() -> list[str]:
    """
    Retrieves a list of names for network interfaces that are Linux bridges.

    It checks for the presence of the 'bridge' subdirectory within
    /sys/class/net/<interface>/, which is the standard indicator that
    an interface is a Linux bridge device. This approach avoids using
    external tools like 'ip' or 'brctl'.

    Returns:
        list[str]: The list of names of the bridge interfaces found.
    """
    assert platform.system() == "Linux"
    bridge_interfaces: list[str] = []

    # Standard path for network interfaces on Linux systems (sysfs)
    net_path: Path = Path("/sys/class/net")

    if not net_path.is_dir():
        # This should exist on Ubuntu, but it's good practice to check
        # Print is in English as it's part of the function's internal output
        print(f"Warning: The path {net_path} is not a directory.")
        return []

    # Iterate over all entries in /sys/class/net
    try:
        for interface_dir in net_path.iterdir():
            # Ensure the element is a directory (which is the case for interfaces)
            if interface_dir.is_dir():
                interface_name: str = interface_dir.name

                # The /sys/class/net/<interface>/bridge directory exists
                # if and only if the interface is a bridge.
                # Check for the existence of the 'bridge' subdirectory
                bridge_indicator_path: Path = interface_dir / "bridge"

                if bridge_indicator_path.is_dir():
                    bridge_interfaces.append(interface_name)

        return bridge_interfaces
    except PermissionError as e:
        raise RuntimeError("Error: Insufficient permissions to read /sys/class/net.") from e
    except Exception as e:
        raise RuntimeError(f"An unexpected error occurred while reading interfaces: {e}") from e


def get_dns_servers() -> tuple[list[ipaddress.IPv4Address], list[ipaddress.IPv6Address]]:
    """
    Reads /etc/resolv.conf and extracts all nameserver IP addresses,
    separating them into IPv4 and IPv6 lists.

    Returns:
        tuple[list[ipaddress.IPv4Address], list[ipaddress.IPv6Address]]:
            A tuple containing the list of IPv4 DNS servers and the list
            of IPv6 DNS servers.
    """
    assert platform.system() == "Linux"
    dns_servers: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []

    with open("/etc/resolv.conf", "r") as f:
        for line in f:
            # Look for lines starting with 'nameserver'
            if line.strip().startswith("nameserver"):
                parts = line.split()
                if len(parts) > 1:
                    # The second part should be the IP address
                    ip_address: str = parts[1]
                    # Note: ipaddress.ip_address() returns the correct type
                    # (IPv4Address or IPv6Address)
                    dns_servers.append(ipaddress.ip_address(ip_address))

    ipv4_list: list[ipaddress.IPv4Address] = []
    ipv6_list: list[ipaddress.IPv6Address] = []

    for addr in dns_servers:
        # Note: In the original Python code, 'addr' is already an IP address object
        # (IPv4Address or IPv6Address) because it was appended as such above.
        # The 'try/except' block and 'ipaddress.ip_address(addr)' call
        # inside the loop are redundant if the parsing above was successful.
        # We simplify the logic here for efficiency and type-correctness
        # based on the objects already in dns_servers.

        # Use the 'version' property of the IP object
        if addr.version == 4:
            # Cast is not strictly necessary here but maintains the original
            # intention of separating the types explicitly.
            ipv4_list.append(cast(ipaddress.IPv4Address, addr))
        elif addr.version == 6:
            ipv6_list.append(cast(ipaddress.IPv6Address, addr))

        # We remove the ValueError block as the original parsing
        # already handled the conversion to IP address objects.

    return ipv4_list, ipv6_list


def get_systemd_resolved_static_dns() -> list[IPv4Address | IPv6Address]:
    """
    Reads the systemd-resolved configuration file to retrieve statically
    configured upstream DNS servers, avoiding external tool execution.

    Note: This only retrieves statically configured servers from the
    resolved.conf file. Dynamically acquired servers (via DHCP/NetworkManager)
    are not visible here and require parsing other configuration files or
    running the 'resolvectl' utility (which is an external tool).

    Returns:
        list[str]: A list of static DNS server IP addresses.
    """
    assert platform.system() == "Linux"
    dns_servers: list[IPv4Address | IPv6Address] = []
    config_path: str = "/run/systemd/resolve/resolv.conf"

    # Regex to capture IP addresses following the 'DNS=' directive
    # It handles multiple IPs separated by spaces.
    dns_pattern: re.Pattern = re.compile(r"^\s*nameserver\s*(.*)$", re.IGNORECASE)

    if not os.path.exists(config_path):
        config_path = "/etc/systemd/resolved.conf"
        if not os.path.exists(config_path):
            return []
    try:
        with open(config_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                # Check for the DNS= line
                match = dns_pattern.match(line)
                if match:
                    # The captured group (1) contains the IP list (e.g., "8.8.8.8 8.8.4.4")
                    ip_list: str = match.group(1).strip()
                    # Split the string by spaces and filter out any empty strings
                    servers_found: list[str] = [ip.strip() for ip in ip_list.split() if ip]
                    dns_servers.extend([ipaddress.ip_address(ip) for ip in servers_found])

        return list(set(dns_servers))
    except IOError as e:
        print(f"Error reading {config_path}: {e}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []

    # Use a set to remove duplicates, then convert back to a sorted list


def get_systemd_resolved_upstream_dns() -> list[IPv4Address | IPv6Address]:
    """
    Executes 'resolvectl status' to retrieve the list of active upstream DNS
    servers from the systemd-resolved service, filtering out the local stub
    resolver IP (127.0.0.53).

    Note: This function explicitly calls the external tool 'resolvectl'
    via subprocess, as required to read the service's dynamic state.

    Returns:
        list[str]: A sorted list of unique, external DNS server IP addresses.
    """
    assert platform.system() == "Linux"
    result = get_systemd_resolved_static_dns()
    if result:
        return result
    try:
        # Execute the resolvectl status command
        resolvectl = shutil.which("resolvectl")
        if resolvectl is None:
            return []
        output = subprocess.run(
            [resolvectl, "status"],
            capture_output=True,
            text=True,
            check=True,  # Raise an error if resolvectl fails
            timeout=5,
        ).stdout

        # Regex to capture the IPs following "Current DNS Server" or "DNS Servers"
        # from both Global and Link configuration sections.
        # Group 2 captures the list of IPs.
        dns_pattern: re.Pattern = re.compile(r"^\s*(Current\s+)?DNS\s+Servers:\s*(.*?)\s*$", re.MULTILINE)

        all_ips: list[IPv4Address | IPv6Address] = []
        # Find all matches across the output
        matches = dns_pattern.findall(output)
        for _, ip_string in matches:
            # Split the captured IP string by space and extend the list
            all_ips.extend([ipaddress.ip_address(ip) for ip in ip_string.split()])
        return list(set(all_ips))
    except FileNotFoundError:
        return []
    except subprocess.CalledProcessError as e:
        logger.debug("Error executing 'resolvectl status': %s", e.stderr.strip())
        return []
    except subprocess.TimeoutExpired:
        logger.debug("'resolvectl status' command timed out.")
        return []
    except Exception as e:
        logger.debug("Unexpected error during resolvectl execution: %s", e)
        return []


# Stub resolver addresses used by systemd-resolved
_STUB_RESOLVERS = {
    ipaddress.ip_address("127.0.0.53"),
    ipaddress.ip_address("127.0.0.54"),
}

# Well-known public DNS servers used as last resort
_FALLBACK_DNS: list[IPv4Address | IPv6Address] = [
    ipaddress.ip_address("1.1.1.1"),
    ipaddress.ip_address("8.8.8.8"),
]


def get_upstream_dns() -> list[IPv4Address | IPv6Address]:
    """Get upstream DNS servers, with or without systemd.

    Tries multiple strategies in order:
    1. systemd-resolved (static config then resolvectl)
    2. /etc/resolv.conf (filtering out stub resolvers like 127.0.0.53)
    3. Well-known public DNS as last resort

    Returns:
        List of upstream DNS server addresses.
    """
    if platform.system() != "Linux":
        return list(_FALLBACK_DNS)

    # Strategy 1: systemd-resolved
    result = get_systemd_resolved_upstream_dns()
    if result:
        return result

    # Strategy 2: /etc/resolv.conf (works on any Linux)
    try:
        ipv4_list, ipv6_list = get_dns_servers()
        all_dns: list[IPv4Address | IPv6Address] = []
        all_dns.extend(ipv4_list)
        all_dns.extend(ipv6_list)
        # Filter out stub resolvers (systemd-resolved writes 127.0.0.53)
        real_dns = [ip for ip in all_dns if ip not in _STUB_RESOLVERS and not ip.is_loopback]
        if real_dns:
            return real_dns
    except (OSError, AssertionError):
        logger.debug("Could not read /etc/resolv.conf")

    # Strategy 3: fallback to well-known public DNS
    logger.debug("Using fallback public DNS servers")
    return list(_FALLBACK_DNS)
