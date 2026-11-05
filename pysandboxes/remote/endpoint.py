# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Where the host and the sandbox talk: a TCP address, a Unix socket path or a VSOCK address.

Kept free of aiohttp so ``daemon_parameters`` and the minimal guest can import it.
"""

import contextlib
import os
import socket
import stat
from typing import Any, NamedTuple

TCP = "tcp"
UNIX = "unix"
VSOCK = "vsock"
FD = "fd"

# sockaddr_un.sun_path is 108 bytes on Linux (107 plus the NUL), 104 on macOS.
_UNIX_PATH_MAX = 103
_VSOCK_ANY = 0xFFFFFFFF


class Endpoint(NamedTuple):
    """One address of the host/sandbox channel.

    Attributes:
        kind: ``tcp``, ``unix``, ``vsock``, or ``fd`` for a listening socket the process inherited.
        host: TCP host, or the VSOCK context id as a decimal string.
        port: TCP or VSOCK port, or the inherited descriptor number for ``fd``.
        path: Absolute path of the Unix socket.
    """

    kind: str
    host: str = ""
    port: int = 0
    path: str = ""


def parse_endpoint(text: str) -> Endpoint:
    """Parse ``tcp://host:port``, ``unix:///abs/path`` or ``vsock://cid:port``.

    Raises:
        ValueError: If the text is not one of these forms.
    """
    scheme, sep, rest = text.partition("://")
    if not sep:
        raise ValueError(f"endpoint {text!r} has no scheme; use tcp://, unix:// or vsock://")
    if scheme == UNIX:
        if not rest.startswith("/"):
            raise ValueError(f"unix endpoint {text!r} needs an absolute path")
        if len(rest.encode()) > _UNIX_PATH_MAX:
            raise ValueError(f"unix endpoint path is longer than {_UNIX_PATH_MAX} bytes")
        return Endpoint(UNIX, path=rest)
    if scheme == FD:
        if not rest.isdigit():
            raise ValueError(f"fd endpoint {text!r} must look like fd://N")
        return Endpoint(FD, port=int(rest))
    if scheme in (TCP, VSOCK):
        host, colon, port_text = rest.rpartition(":")
        if not colon or not host or not port_text.isdigit():
            raise ValueError(f"{scheme} endpoint {text!r} must look like {scheme}://host:port")
        if scheme == VSOCK and host != "any" and not host.isdigit():
            raise ValueError(f"vsock endpoint {text!r} needs a numeric context id or 'any'")
        return Endpoint(scheme, host=host, port=int(port_text))
    raise ValueError(f"unknown endpoint scheme {scheme!r}; use tcp, unix, vsock or fd")


def format_endpoint(endpoint: Endpoint) -> str:
    """Return the text form that :func:`parse_endpoint` reads back."""
    if endpoint.kind == UNIX:
        return f"{UNIX}://{endpoint.path}"
    if endpoint.kind == FD:
        return f"{FD}://{endpoint.port}"
    return f"{endpoint.kind}://{endpoint.host}:{endpoint.port}"


def _address(endpoint: Endpoint) -> tuple[int, str | tuple[str, int] | tuple[int, int]]:
    if endpoint.kind == FD:
        raise ValueError("an inherited descriptor has no address to bind or connect to")
    if endpoint.kind == UNIX:
        return socket.AF_UNIX, endpoint.path
    if endpoint.kind == VSOCK:
        if not hasattr(socket, "AF_VSOCK"):
            raise OSError("this platform has no AF_VSOCK")
        cid = _VSOCK_ANY if endpoint.host == "any" else int(endpoint.host)
        return socket.AF_VSOCK, (cid, endpoint.port)
    return socket.AF_INET, (endpoint.host, endpoint.port)


def client_socket(endpoint: Endpoint) -> tuple[socket.socket, Any]:
    """Return a new non-blocking socket and the address to connect it to."""
    family, address = _address(endpoint)
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setblocking(False)
    return sock, address


def listen_socket(endpoint: Endpoint) -> socket.socket:
    """Bind and listen on the endpoint; a Unix socket is created with mode 0600.

    A stale socket file left by a dead daemon is replaced; anything else at that path is an error.
    """
    family, address = _address(endpoint)
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if endpoint.kind == UNIX:
            with contextlib.suppress(FileNotFoundError):
                if not stat.S_ISSOCK(os.lstat(endpoint.path).st_mode):
                    raise FileExistsError(f"{endpoint.path} exists and is not a socket")
                os.unlink(endpoint.path)
            previous = os.umask(0o177)
            try:
                sock.bind(address)
            finally:
                os.umask(previous)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(address)
        sock.listen(socket.SOMAXCONN)
        sock.setblocking(False)
    except BaseException:
        sock.close()
        raise
    return sock


def adopt_listener(endpoint: Endpoint) -> socket.socket:
    """Wrap the listening socket a parent bound and handed down as descriptor ``endpoint.port``."""
    sock = socket.socket(fileno=endpoint.port)
    sock.setblocking(False)
    return sock


def remove_endpoint(endpoint: Endpoint) -> None:
    """Delete the socket file of a Unix endpoint; other kinds leave nothing behind."""
    if endpoint.kind == UNIX:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(endpoint.path)
