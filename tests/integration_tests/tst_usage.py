import asyncio
import io
import logging
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path
from socket import AF_INET, AF_INET6, SOCK_DGRAM, SOCK_STREAM
from types import FrameType
from typing import Any, List, Mapping, cast

from pysandboxes import SandBoxError, is_in_sandbox, sandbox, sandboxes
from pysandboxes.learning import is_learning_mode
from pysandboxes.remote.python_in_sb import convert_extra_rules

logger = logging.getLogger(__name__)


RANGETEST = 1


def init_log_level(use_rich: bool = True) -> None:
    handlers: list[logging.Handler] = []
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

    if not handlers:
        handlers = [logging.StreamHandler()]
        handlers[0].setFormatter(logging.Formatter(format))

    sandboxes_level = logging.DEBUG
    uvicorn_level = logging.ERROR
    logging.getLogger("uvicorn").setLevel(uvicorn_level)
    logging.getLogger("asyncio").setLevel(uvicorn_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_level)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandboxes_level)
    logging.getLogger().setLevel(sandboxes_level)  # Set the default level for root
    logging.basicConfig(
        force=True,
        level=min(sandboxes_level, logging.INFO),
        format=format,
        handlers=handlers,
    )
    # logging.error("ERROR test")
    # logging.warning("WARNING test")
    # logging.info("INFO test")
    # logging.debug("DEBUG test")


def signal_handler_main(
    signum: int, frame: FrameType | None
) -> Any | int | signal.Handlers:
    logger.info("********** catch signal in main")
    return None


_old_sigint_handler = None


def signal_handler_sandbox(
    signum: int, frame: FrameType | None
) -> Any | int | signal.Handlers:
    global _old_sigint_handler
    logger.info("********** catch signal in sandbox")
    if callable(_old_sigint_handler):
        return _old_sigint_handler(signum, frame)
    return None


@sandbox
async def arun_in_sandbox() -> int:
    logger.info("Run 'arun_in_sandbox()' in sandbox")
    _test_envs()
    _test_files()
    _test_network()
    print("end of arun_in_sandbox()")
    global _old_sigint_handler
    _old_sigint_handler = signal.signal(signal.SIGTERM, signal_handler_sandbox)

    print(f"arun_in_sandbox {threading.current_thread()=}")

    # os.kill(os.getpid(),signal.SIGTERM)
    # await asyncio.sleep(5)
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
    os.putenv("My_ENV", "hello")
    os.getenv("My_ENV")
    os.unsetenv("My_ENV")
    learning_mode = is_learning_mode()
    if "OS_SANDBOX" in os.environ:
        learning_mode = os.environ["OS_SANDBOX"].lower() == "none"

    if not learning_mode:
        assert "USER" not in os.environ, "USER must not be visible"


def _test_network() -> None:
    # tcp connection
    import socket

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
    if "OS_SANDBOX" in os.environ:
        learning_mode = os.environ["OS_SANDBOX"].lower() == "none"
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
                sock.bind(("127.0.0.1", 9998))
            assert learning_mode, "Must be stopped by pysandbox"
        except SandBoxError:
            print("Connect to github is stopped")
        try:
            with socket.socket(AF_INET6, SOCK_STREAM) as sock:
                sock.bind(("::1", 9998))
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
    learning_mode = is_learning_mode()
    if "OS_SANDBOX" in os.environ:
        learning_mode = os.environ["OS_SANDBOX"].lower() == "none"
    if not learning_mode:
        # Check access refused
        try:
            with io.open("hack.py", "w"):
                pass
            assert learning_mode, "Must be stopped by pysandbox"
        except SandBoxError:
            print("Write to hack.py is stopped")

        try:
            with tempfile.TemporaryFile(mode="w+") as _:
                pass
            assert learning_mode, "Must be stopped by pysandbox"
        except SandBoxError:
            print("Write to TemporaryFile is stopped")

        try:
            with tempfile.NamedTemporaryFile(mode="w+", delete=True) as _:
                pass
            assert learning_mode, "Must be stopped by pysandbox"
        except SandBoxError:
            print("Write to NamedTemporaryFile is stopped")


async def ainit_sandbox() -> None:
    logger.error("INIT Daemon")


async def async_manager() -> None:
    for _ in range(0, 2):
        async with sandboxes(init_fn=init_sandbox):
            assert await arun() == 42


# %% --------------------------------------
def init_sandbox() -> None:
    init_log_level()
    if is_in_sandbox():
        signal.signal(signal.SIGQUIT, signal_handler_sandbox)
    else:
        signal.signal(signal.SIGQUIT, signal_handler_main)
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


async def async_main(argv: List[str]) -> int:
    init_log_level()

    os.environ["LLM_TOKEN"] = "abc"

    config_path, extra_rules = _config(argv)
    for _ in range(0, RANGETEST):
        async with sandboxes(
            async_init_sandbox,
            sandboxes_config=config_path,
            **cast(Mapping[str, Any], extra_rules),
        ):
            await arun()
            # logger.info("async_main.kill...")
            # os.kill(os.getpid(), signal.SIGTERM)
            # logger.info("async_main.kill... done")
            # await asyncio.sleep(5)  # The signal may be catch

    logger.info("async_main.return 0")
    return 0


def sync_main(argv: List[str]) -> int:
    init_log_level()

    os.environ["LLM_TOKEN"] = "abc"

    config_path, extra_rules = _config(argv)

    for _ in range(0, RANGETEST):
        with sandboxes(
            init_sandbox,
            sandboxes_config=config_path,
            **cast(Mapping[str, Any], extra_rules),
        ):
            logger.info("sync_main.run...")
            run()
            logger.info("sync_main.run...done")
            # logger.info("sync_main.kill...")
            # os.kill(os.getpid(), signal.SIGTERM)
            # logger.info("sync_main.kill done")

    return 0


def _config(argv: list[str]) -> tuple[Path, dict[str, set[str]]]:
    extra_rules = convert_extra_rules(argv[1:])
    config_path = Path("tests/integration_tests/py-sandbox-test.profile")
    if "learn" in extra_rules:
        learning_path, *_ = extra_rules.get("learn", set())
        if not learning_path:
            learning_path = ".py-sandboxes"
        extra_rules["learn"] = {learning_path}
    return config_path, extra_rules


# from pysandboxes.sandboxes_api import sandboxes
#
# def init_sandbox():
#     print("init")
#
# def main():
#     with sandboxes(init_fn=init_sandbox):
#         print("ok")

if __name__ == "__main__":
    init_log_level()
    # sync_main(sys.argv)
    logger.info("-------------------------")
    asyncio.run(async_main(sys.argv))
    logger.info("End of __main__")
