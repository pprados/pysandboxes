# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`Endpoint`: parsing, listening and connecting over TCP, Unix sockets and VSOCK addresses."""

import asyncio
import os
import shutil
import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest  # type: ignore[import-untyped]
from aiohttp import ClientConnectorError, ClientSession, web

from pysandboxes.remote.endpoint import (
    FD,
    TCP,
    UNIX,
    VSOCK,
    Endpoint,
    adopt_listener,
    client_socket,
    format_endpoint,
    listen_socket,
    parse_endpoint,
    remove_endpoint,
)
from pysandboxes.remote.endpoint_connector import ENDPOINT_URL, EndpointConnector, make_session
from tests.unit_tests._unix_sockets import requires_unix_sockets


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A short path: a Unix socket address is limited to about 100 bytes, which pytest's tmp_path exceeds."""
    path = Path(tempfile.mkdtemp(prefix="pysb-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("tcp://127.0.0.1:8080", Endpoint(TCP, host="127.0.0.1", port=8080)),
        ("unix:///run/sb.sock", Endpoint(UNIX, path="/run/sb.sock")),
        ("vsock://3:5000", Endpoint(VSOCK, host="3", port=5000)),
        ("vsock://any:5000", Endpoint(VSOCK, host="any", port=5000)),
        ("fd://7", Endpoint(FD, port=7)),
    ],
)
def test_every_kind_round_trips(text: str, expected: Endpoint) -> None:
    assert parse_endpoint(text) == expected
    assert format_endpoint(expected) == text


@pytest.mark.parametrize(
    "text",
    [
        "127.0.0.1:80",
        "ftp://host:1",
        "tcp://host",
        "tcp://:80",
        "tcp://host:port",
        "unix://relative/path",
        "unix://" + "/a" * 60,
        "vsock://host:5",
        "vsock://3",
        "fd://x",
        "fd://",
    ],
)
def test_a_malformed_endpoint_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_endpoint(text)


def test_vsock_without_platform_support_is_an_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(socket, "AF_VSOCK", raising=False)

    with pytest.raises(OSError, match="AF_VSOCK"):
        client_socket(Endpoint(VSOCK, host="3", port=1))


@pytest.mark.skipif(not hasattr(socket, "AF_VSOCK"), reason="no AF_VSOCK on this platform")
def test_vsock_address_uses_the_cid_and_port() -> None:
    try:
        sock, address = client_socket(Endpoint(VSOCK, host="3", port=5000))
    except OSError:
        pytest.skip("the kernel offers no vsock transport")
    sock.close()
    assert address == (3, 5000)


@requires_unix_sockets
def test_a_unix_socket_is_private_and_removed(short_dir: Path) -> None:
    endpoint = Endpoint(UNIX, path=str(short_dir / "s"))

    sock = listen_socket(endpoint)
    try:
        assert stat.S_IMODE(os.stat(endpoint.path).st_mode) == 0o600
    finally:
        sock.close()
    remove_endpoint(endpoint)

    assert not os.path.exists(endpoint.path)
    remove_endpoint(endpoint)


@requires_unix_sockets
def test_a_stale_unix_socket_is_replaced(short_dir: Path) -> None:
    endpoint = Endpoint(UNIX, path=str(short_dir / "s"))
    listen_socket(endpoint).close()

    listen_socket(endpoint).close()


@requires_unix_sockets
def test_a_regular_file_is_never_replaced(short_dir: Path) -> None:
    target = short_dir / "s"
    target.write_text("data")

    with pytest.raises(FileExistsError):
        listen_socket(Endpoint(UNIX, path=str(target)))

    assert target.read_text() == "data"


async def _serve(sock: socket.socket) -> web.AppRunner:
    app = web.Application()

    async def ping(_: web.Request) -> web.Response:
        return web.json_response({"message": "OK"})

    app.router.add_get("/ping", ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    return runner


@requires_unix_sockets
async def test_a_request_crosses_a_unix_socket(short_dir: Path) -> None:
    endpoint = Endpoint(UNIX, path=str(short_dir / "s"))
    runner = await _serve(listen_socket(endpoint))
    try:
        async with make_session(endpoint) as session, session.get(ENDPOINT_URL + "/ping") as response:
            assert await response.json() == {"message": "OK"}
    finally:
        await runner.cleanup()


async def test_a_request_crosses_tcp() -> None:
    sock = listen_socket(Endpoint(TCP, host="127.0.0.1", port=0))
    endpoint = Endpoint(TCP, host="127.0.0.1", port=sock.getsockname()[1])
    runner = await _serve(sock)
    try:
        async with make_session(endpoint) as session, session.get(f"http://127.0.0.1:{endpoint.port}/ping") as r:
            assert await r.json() == {"message": "OK"}
    finally:
        await runner.cleanup()


@requires_unix_sockets
async def test_a_missing_socket_is_a_connector_error(short_dir: Path) -> None:
    endpoint = Endpoint(UNIX, path=str(short_dir / "absent"))

    async with make_session(endpoint) as session:
        with pytest.raises(ClientConnectorError):
            await session.get(ENDPOINT_URL + "/ping")


@requires_unix_sockets
async def test_the_client_may_start_before_the_server(short_dir: Path) -> None:
    endpoint = Endpoint(UNIX, path=str(short_dir / "s"))
    async with ClientSession(connector=EndpointConnector(endpoint)) as session:
        with pytest.raises(ClientConnectorError):
            await session.get(ENDPOINT_URL + "/ping")
        runner = await _serve(listen_socket(endpoint))
        try:
            await asyncio.sleep(0)
            async with session.get(ENDPOINT_URL + "/ping") as response:
                assert response.status == 200
        finally:
            await runner.cleanup()


def test_an_inherited_descriptor_is_adopted_as_the_same_listener() -> None:
    sock = listen_socket(Endpoint(TCP, host="127.0.0.1", port=0))
    descriptor = os.dup(sock.fileno())
    try:
        adopted = adopt_listener(Endpoint(FD, port=descriptor))
        assert adopted.getsockname() == sock.getsockname()
        assert not adopted.getblocking()
        adopted.close()
    finally:
        sock.close()


def test_an_inherited_descriptor_has_no_address_to_connect_to() -> None:
    with pytest.raises(ValueError):
        client_socket(Endpoint(FD, port=3))
