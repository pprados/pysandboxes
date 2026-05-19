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
import ipaddress
import logging
import os
import pickle
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
from typing import Any, cast

logger = logging.getLogger(__name__)

known_paths = [
    Path("/bin/"),
    Path("/usr/bin/"),
    Path("/usr/local/bin/"),
]


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

        distro_id: str = distro_info.get(
            "ID", ""
        ).lower()  # Get the ID of the distribution

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
            logging.warning(
                "prctl(PR_SET_PDEATHSIG, SIGTERM) failed with code %s", result
            )
    except OSError:
        logging.warning("prctl not available (not Linux or libc not found).")


def to_b85(obj: Any) -> str:
    """Serialize object to base85-encoded string.

    Args:
        obj: Object to serialize.

    Returns:
        Base85-encoded serialized object string.
    """
    result = base64.b85encode(
        # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle — reason: serialization only
        pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    ).decode("ascii")
    # reason: round-trip check on locally built data
    # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
    assert pickle.loads(base64.b85decode(result.encode("ascii"))) == obj
    return result


def from_b85(b85: str) -> Any:
    """Deserialize object from base85-encoded string.

    Args:
        b85: Base85-encoded string.

    Returns:
        Deserialized object.
    """
    # reason: IPC transport; child->parent results are untrusted (open issue)
    # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
    return pickle.loads(
        base64.b85decode(b85.encode("ascii")),
    )


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
        result = subprocess.run(
            ["ip", "route"], capture_output=True, text=True, check=True, timeout=5
        )
        output: str = result.stdout

        # 2. Search for the default route line
        # The line typically starts with 'default via <gateway_ip> dev <interface_name>'
        # Example: 'default via 192.168.1.1 dev eth0 proto dhcp src 192.168.1.100 metric 100'
        # We use a regex to capture the 'dev <interface_name>' part
        default_route_pattern: re.Pattern = re.compile(
            r"^default\s+.*dev\s+(\S+)", re.MULTILINE
        )

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
        logger.warning(
            "Error: 'ip' command not found. Ensure iproute2 package is installed."
        )
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
        raise RuntimeError(
            "Error: Insufficient permissions to read /sys/class/net."
        ) from e
    except Exception as e:
        raise RuntimeError(
            f"An unexpected error occurred while reading interfaces: {e}"
        ) from e


def get_dns_servers() -> (
    tuple[list[ipaddress.IPv4Address], list[ipaddress.IPv6Address]]
):
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
                    servers_found: list[str] = [
                        ip.strip() for ip in ip_list.split() if ip
                    ]
                    dns_servers.extend(
                        [ipaddress.ip_address(ip) for ip in servers_found]
                    )

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
        dns_pattern: re.Pattern = re.compile(
            r"^\s*(Current\s+)?DNS\s+Servers:\s*(.*?)\s*$", re.MULTILINE
        )

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
        real_dns = [
            ip for ip in all_dns if ip not in _STUB_RESOLVERS and not ip.is_loopback
        ]
        if real_dns:
            return real_dns
    except (OSError, AssertionError):
        logger.debug("Could not read /etc/resolv.conf")

    # Strategy 3: fallback to well-known public DNS
    logger.debug("Using fallback public DNS servers")
    return list(_FALLBACK_DNS)
