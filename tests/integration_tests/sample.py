import logging
import sys
from pathlib import Path
from typing import NoReturn

from pysandboxes import sandbox, sandboxes

logger = logging.getLogger(__name__)

config_path = Path(__file__).parent / "py-sandbox-test.profile"
assert config_path.exists()


def init_sandbox() -> None:
    logger.info("init_sandbox called")


@sandbox
async def arun_in_sandbox() -> int:
    print(42)
    return 42


@sandbox
def run_in_sandbox() -> int:
    print(42)
    return 42


@sandbox
def raise_in_sandbox() -> NoReturn:
    raise ValueError("raised inside the sandbox")


@sandbox
def raise_sandbox_error_in_sandbox() -> NoReturn:
    """Raise the framework's own base error, from application code."""
    from pysandboxes.e import SandBoxError

    raise SandBoxError("raised by the application, not by the transport")


async def async_forty_two() -> int:
    rc = await arun_in_sandbox()
    assert rc == 42
    return rc


def sync_forty_two() -> int:
    rc = run_in_sandbox()
    assert rc == 42
    return rc


def sync_sanboxes(config_path: Path) -> None:
    with sandboxes(init_sandbox, sandboxes_config=config_path):
        assert sync_forty_two() == 42


async def async_sanboxes(config_path: Path) -> None:
    async with sandboxes(init_sandbox, sandboxes_config=config_path):
        assert await async_forty_two() == 42


async def bridge_async_to_sync(config_path: Path) -> None:
    sync_sanboxes(config_path)


@sandbox
def sync_print_stdin_stdout() -> None:
    print("hello")
    print("world", file=sys.stderr)


@sandbox
async def async_print_stdin_stdout() -> None:
    print("hello")
    print("world", file=sys.stderr)


@sandbox
def connect_outside_the_rules() -> str:
    """Reach an address no profile allows.

    An IP literal from TEST-NET-3 (RFC 5737), so the guard refuses before any
    packet leaves and the test needs neither a resolver nor a reachable host. A
    hostname would need ``encodings.idna``, which a profile learned from a run
    that never resolved a name does not carry: the call would then fail on
    ``LookupError: unknown encoding: idna`` instead of on the rule.
    """
    import socket

    # connect() on an AF_INET socket rather than create_connection(), which
    # calls getaddrinfo() and encodes the host through ``encodings.idna`` even
    # for a literal address.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(8)
    try:
        s.connect(("203.0.113.1", 443))
    finally:
        s.close()
    return "connected"
