import asyncio
import io
import logging
import os
import sys
import tempfile
from pathlib import Path
from socket import AF_INET, AF_INET6, SOCK_DGRAM, SOCK_STREAM
from typing import Any, List, Mapping, cast

from pysandboxes import SandBoxError, sandbox, sandboxes
from pysandboxes.learning import is_learning_mode
from pysandboxes.remote.python_in_sb import convert_extra_rules

logger = logging.getLogger(__name__)


def init_log_level(use_rich: bool = True) -> None:
    handlers = []
    format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
    if use_rich:
        try:
            from rich.console import Console
            from rich.logging import RichHandler

            # Active RichHandler if possible.
            handlers.append(
                RichHandler(
                    console=Console(stderr=True),
                    rich_tracebacks=False,
                    log_time_format="[%X]",
                    show_time=True,
                )
            )
            format = "[%(process)d] %(message)s"
        except ImportError:
            pass  # Ignore

    sandboxes_level = logging.WARNING  # FIXME
    uvicorn_level = logging.ERROR
    logging.getLogger("asyncio").setLevel(uvicorn_level)
    logging.getLogger("uvicorn").setLevel(uvicorn_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_level)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandboxes_level)
    logging.getLogger().setLevel(sandboxes_level)  # Set the default level for root
    logging.basicConfig(
        level=min(sandboxes_level, logging.INFO),
        format=format,
        handlers=handlers)
    # logging.error("ERROR test")
    # logging.warning("WARNING test")
    # logging.info("INFO test")
    # logging.debug("DEBUG test")


@sandbox
async def arun_in_sandbox() -> int:
    logger.info("Run 'arun_in_sandbox()' in sandbox")
    _test_envs()
    _test_files()
    _test_network()
    print("end of arun_in_sandbox()")
    return 42


@sandbox
def run_in_sandbox() -> int:
    logger.info("Run 'run_in_sandbox()' in sandbox")
    _test_envs()
    _test_files()
    _test_network()
    print(42)
    return 42


def _test_envs() -> None:
    assert os.environ["LANGUAGE"]
    os.putenv("My_ENV","hello")
    os.getenv("My_ENV")
    if not is_learning_mode():
        assert "USER" not in os.environ,"USER must not be visible"



def _test_network() -> None:
    # tcp connection
    import socket

    import pysandboxes.learning
    # 1. Learn and accept
    # Learn a direct connection to google
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        remote_ip = socket.gethostbyname("www.google.com")
        socket.gethostbyname_ex("www.google.com")
        socket.getaddrinfo("www.google.com", None, family=socket.AF_UNSPEC)
        sock.connect((remote_ip, 80))

    # learn tcp bind ipv4
    with socket.socket(AF_INET, SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 9999))
    # learn tcp bind ipv6
    with socket.socket(AF_INET6, SOCK_STREAM) as sock:
        sock.bind(("::1", 9999))

    # web connection
    import requests

    requests.get("http://www.google.com/")

    # udp connection ipv4
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"hello", ("127.0.0.1", 12345))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"hello", ("127.0.0.1", 12346))
    # udp connection ipv6
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"hello", ("::1", 12345))
    # udp bind ipv4
    with socket.socket(AF_INET, SOCK_DGRAM) as sock:
        sock.bind(("localhost", 12345))
    # udp bind ipv6
    with socket.socket(AF_INET6, SOCK_STREAM) as sock:
        sock.bind(("::1", 9999))

    # 2. Test denied access
    learning_mode = is_learning_mode()
    if not learning_mode:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                remote_ip = socket.gethostbyname("www.github.com")
                sock.connect((remote_ip, 80))
            assert learning_mode, "Must be stopped by pysandbox"
        except SandBoxError:
            print("Connect to github is stopped")

        try:
            with socket.socket(AF_INET, SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
            assert learning_mode, "Must be stopped by pysandbox"
        except SandBoxError:
            print("Connect to github is stopped")
        try:
            with socket.socket(AF_INET6, SOCK_STREAM) as sock:
                sock.bind(("::1", 12345))
            assert learning_mode, "Must be stopped by pysandbox"
        except SandBoxError:
            print("Connect to github is stopped")


def _test_files() -> None:
    print("---- Test files")
    learning_mode = is_learning_mode()

    # 1. Learn and accept
    with io.open("tmp/test.remove", "w") as _:
        pass

    # 2. Test denied access
    if not is_learning_mode():
        # Check access refused
        try:
            with io.open("hack.py", "w"):
                pass
            assert learning_mode, "Must be stopped by pysandbox"
        except SandBoxError:
            print("Write to hack.py is stopped")

        with tempfile.TemporaryFile(mode="w+") as _:
            pass
        print("Write to TemporaryFile is accepted")

        with tempfile.NamedTemporaryFile(mode="w+", delete=True) as _:
            pass
        print("Write to NamedTemporaryFile is accepted")


async def ainit_sandbox() -> None:
    logger.error("INIT Daemon")


async def async_manager() -> None:
    for _ in range(0, 2):
        async with sandboxes(init_fn=init_sandbox):
            assert await arun() == 42


# %% --------------------------------------
def init_sandbox() -> None:
    init_log_level()
    logger.debug("INIT sandbox")


async def async_init_sandbox() -> None:
    init_sandbox()


async def arun() -> int:
    rc = await arun_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    return rc


def run() -> int:
    rc = run_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    return rc


@sandbox
def _call_llm(token: str) -> None:
    print(f"{token=}")


def call_llm() -> None:
    _call_llm(token=os.environ["USER"])


async def main(argv: List[str]) -> int:
    init_log_level()
    os.environ["LLM_TOKEN"] = "abc"

    # def audit_hook(event, args):
    #     logger.debug(f'Audit event: {event} {" XX ,".join(map(repr, args))}')
    # import sys
    # sys.addaudithook(audit_hook)

    extra_rules = convert_extra_rules(argv[1:])
    config_path = Path("tests/test.py-sandboxes")
    if "learn" in extra_rules:
        learning_path, *_ = extra_rules.get("learn", set())
        if not learning_path:
            learning_path = ".py-sandboxes"
        extra_rules["learn"] = {learning_path}

    for _ in range(0, 1):
        async with sandboxes(
                async_init_sandbox,
                sandboxes_config=config_path,
                **cast(Mapping[str, Any], extra_rules),
        ):
            await arun()
    return 0


# from pysandboxes.sandboxes_api import sandboxes
#
# def init_sandbox():
#     print("init")
#
# def main():
#     with sandboxes(init_fn=init_sandbox):
#         print("ok")

if __name__ == "__main__":

    try:
        asyncio.run(main(sys.argv))
    except KeyboardInterrupt:
        pass
