# TODO: reorganize the tools
import asyncio
import base64
import contextvars
import inspect
import logging
import os
import pickle
import shutil
import signal
import sys  # Import the sys module to access system-specific parameters and functions
import textwrap
from ctypes import cdll
from pathlib import Path
from typing import Any, Optional, Dict, Tuple, Awaitable, Callable

import netifaces

logger = logging.getLogger(__name__)


END_OF_FILE="---------- END OF FILE ----------\n"

def to_b85(obj: Any) -> str:
    return base64.b85encode(
        pickle.dumps(obj,
                     protocol=pickle.HIGHEST_PROTOCOL
                     )).decode("utf-8")


def from_b85(b85: str) -> Any:
    return pickle.loads(
        base64.b85decode(b85.encode("utf-8")),
    )


known_paths = [
    Path("/bin/"),
    Path("/usr/bin/"),
    Path("/usr/local/bin/"),
]


def which_command(command: str) -> Optional[Path]:
    for path in known_paths:
        if (path / command).exists():
            return path / command
    full_path = shutil.which(command)
    if not full_path:
        return None
    return Path(full_path)


def get_venv() -> str | None:
    """
    Détecte le répertoire de l'environnement virtuel en comparant sys.prefix et sys.base_prefix.
    """
    if sys.prefix != sys.base_prefix:
        venv_path = sys.prefix
        return venv_path
    else:
        return os.environ.get('VIRTUAL_ENV')


def configure_logging_level(verbose_count: int) -> int:
    """
    Configures the logging level based on the number of verbose flags.

    Args:
        verbose_count (int): The number of '-v' flags provided by the user.
                             - 0: WARNING
                             - 1: INFO
                             - 2: DEBUG
                             - 3+: NOTSET (all messages, including custom trace levels if defined)
    """
    if verbose_count == 0:
        log_level = logging.WARNING
    elif verbose_count == 1:
        log_level = logging.INFO
    elif verbose_count == 2:
        log_level = logging.DEBUG
    else:  # verbose_count >= 3
        # NOTSET will log all messages, allowing custom levels below DEBUG if implemented
        log_level = logging.NOTSET

    logging.getLogger().setLevel(log_level)  # Root logger
    return log_level


def get_default_gateway_info() -> Optional[Tuple[str, str]]:
    gws: Dict[str, Any] = netifaces.gateways()

    # Retrieve default IPv4 gateway
    try:
        if netifaces.AF_INET in gws['default']:
            # The structure for default gateway is (gateway_ip, interface_name, is_primary)
            ipv4_gateway_data = gws['default'][netifaces.AF_INET]
            return ipv4_gateway_data

        # Retrieve default IPv6 gateway
        if netifaces.AF_INET6 in gws['default']:
            # The structure for default gateway is (gateway_ip, interface_name, is_primary)
            ipv6_gateway_data = gws['default'][
                netifaces.AF_INET6]
            return ipv6_gateway_data
    except KeyError:
        # No default gateway found for the specified address family
        pass
    return None


def suggest_package_installation(package_name: str) -> str:
    """
    Suggests how to install a given package based on the detected operating system and Linux distribution.

    Args:
        package_name (str): The name of the package to suggest installation for.
    """
    system: str = sys.platform  # Get the operating system name (e.g., 'linux', 'darwin', 'win32')

    if system.startswith('linux'):
        # Try to identify the specific Linux distribution
        distro_info: dict[str, str] = {}
        try:
            # Read /etc/os-release for detailed distribution information
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        key, value = line.split('=', 1)
                        distro_info[key] = value.strip('"')
        except FileNotFoundError:
            # Fallback for older systems that might use /etc/lsb-release
            try:
                with open('/etc/lsb-release', 'r') as f:
                    for line in f:
                        line = line.strip()
                        if '=' in line:
                            key, value = line.split('=', 1)
                            distro_info[key] = value.strip('"')
            except FileNotFoundError:
                pass  # No specific distro info found

        distro_id: str = distro_info.get('ID',
                                         '').lower()  # Get the ID of the distribution

        if distro_id == 'ubuntu' or distro_id == 'debian':
            return f"sudo apt update && sudo apt install {package_name}"
        elif distro_id == 'fedora':
            return f"sudo dnf install {package_name}"
        elif distro_id == 'centos' or distro_id == 'rhel':
            return f"sudo yum install {package_name}"
        elif distro_id == 'arch':
            return f"sudo pacman -S {package_name}"
        else:
            # Fallback for unknown or other Linux distributions
            return textwrap.dedent(f"""
                You can try installing '{package_name}' using common package managers like:
                sudo apt update && sudo apt install {package_name}  (Debian/Ubuntu based systems)
                sudo yum install {package_name}          (CentOS/RHEL based systems)
                sudo dnf install {package_name}          (Fedora based systems)
                sudo pacman -S {package_name}            (Arch Linux based systems)
                Please refer to your distribution's documentation for the correct command.
                """).strip()

    elif system == 'darwin':
        # For macOS, suggest Homebrew
        return textwrap.dedent(f"""
            /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
            brew install {package_name}
            """).strip()
    elif system == 'win32':
        # For Windows, suggest Winget or Chocolatey
        return textwrap.dedent(f"""
            You can try installing '{package_name}' using:")
              winget install {package_name}            (Windows Package Manager)
              choco install {package_name}             (Chocolatey - if installed)
            You might need to install Winget or Chocolatey first if you don't have them.
            """).strip()
    else:
        # For other or unknown systems
        return textwrap.dedent(f"""
            Your operating system ({system}) is not explicitly supported.
            Please refer to the documentation for '{package_name}' to find installation instructions for your system.
            """).strip()


def return_level_parameter(log_level:int) -> str:
    _map = {
        logging.WARN: "",
        logging.INFO: "-v",
        logging.DEBUG: "-vv",
        logging.NOTSET: "-vvv",
    }
    return _map.get(log_level, logging.NOTSET)


def create_daemon_task(
    coro: Awaitable[object],
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> asyncio.Task[object]:
    """
    Schedule *coro* as a fire-and-forget task that will not raise warnings
    if cancelled and whose exceptions are logged instead of propagating.
    """
    async def _run() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            # Silent cancellation → like a daemon stopping with the loop
            logger.debug("Cancelled daemon task. Ignore")
            pass
        except Exception as exc:  # noqa: BLE001
            logging.exception("Unhandled exception in daemon task: %s", exc)

    loop = loop or asyncio.get_running_loop()
    task = loop.create_task(_run(), name="daemon")
    # Ensure exception retrieval → no "Task exception was never retrieved"
    def is_canceled(t: asyncio.Task[object]):
        logger.debug(f"{t.cancelled()}")
    # task.add_done_callback(lambda t: t.exception())
    task.add_done_callback(is_canceled)
    return task



# Constant from linux/prctl.h
PR_SET_PDEATHSIG = 1

def set_pdeathsig() -> None:
    """
    Sets the PR_SET_PDEATHSIG option for the current process,
    so it receives SIGTERM if its parent dies.
    """
    if os.name != 'posix':
        logger.warning("set_pdeathsig() not supported on non-POSIX systems.")
        return
    try:
        # Load libc and call prctl
        libc = cdll.LoadLibrary("libc.so.6")
        result = libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
        if result != 0:
            logging.warning("prctl(PR_SET_PDEATHSIG, SIGTERM) failed with code %s",result)
    except OSError:
        logging.warning("prctl not available (not Linux or libc not found).")

