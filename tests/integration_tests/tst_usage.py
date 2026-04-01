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
from pysandboxes.config import RELEASE
from pysandboxes.learning import is_learning_mode
from pysandboxes.remote.python_in_sb import convert_extra_rules

logger = logging.getLogger(__name__)

OK: str = "\u2705\ufe0f "
KO: str = "\u274c\ufe0f "

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

    if not RELEASE:
        sandboxes_level = logging.DEBUG
    else:
        sandboxes_level = logging.INFO

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
async def arun_in_sandbox() -> tuple[int, int]:
    logger.info("---- Run 'arun_in_sandbox()' in sandbox")
    rc = 0
    rc += _test_envs()
    rc += _test_files()
    rc += _test_network()
    global _old_sigint_handler
    _old_sigint_handler = signal.signal(signal.SIGTERM, signal_handler_sandbox)

    logger.info(f"arun_in_sandbox {threading.current_thread()=}")

    # os.kill(os.getpid(),signal.SIGTERM)
    # await asyncio.sleep(5)
    return 42, rc


@sandbox
def run_in_sandbox() -> tuple[int, int]:
    logger.info("---- Run 'run_in_sandbox()' in sandbox")
    rc = 0
    rc += _test_envs()
    rc += _test_files()
    rc += _test_network()
    return 42, rc


def _test_envs() -> int:
    rc = 0
    if "TERM" not in os.environ:
        logger.error(f"{KO} TERM must be in os.environ")
        rc = 1
    else:
        logger.info(f"{OK} TERM is visible")

    # os.putenv("My_ENV", "hello")
    if "My_ENV" in os.environ:
        os.getenv("My_ENV")
        os.unsetenv("My_ENV")
        logger.info(f"{OK} My_ENV is visible")
    else:
        logger.error(f"{KO} My_ENV must be in os.environ")
        rc = 1

    learning_mode = is_learning_mode()
    if "OS_SANDBOX" in os.environ:
        learning_mode = os.environ["OS_SANDBOX"].lower() == "none"

    if not learning_mode:
        if "USER" in os.environ:
            logger.error(f"{KO} USER must not be visible")
            rc = 1
        else:
            logger.info(f"{OK} USER is not visible")
    return rc


def _test_network() -> int:
    # tcp connection
    import socket

    rc = 0

    timeout = 3

    # 1. Learn and accept
    # Learn a direct connection to google
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            remote_ip = socket.gethostbyname("www.google.com")
            socket.gethostbyname_ex("www.google.com")
            socket.getaddrinfo("www.google.com", None, family=socket.AF_UNSPEC)
            sock.settimeout(timeout)
            sock.connect((remote_ip, 80))
            logger.info(f"{OK} socker AF_INET SOCK_STREAM 80")
    except SandBoxError:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80")
        rc = 1
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    # learn tcp bind ipv4
    try:
        with socket.socket(AF_INET, SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.bind(("127.0.0.1", 9999))
            logger.info(f"{OK} socker AF_INET SOCK_STREAM 9999")
    except SandBoxError:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 9999")
        rc = 1
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    # learn tcp bind ipv6
    try:
        with socket.socket(AF_INET6, SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.bind(("::1", 9999))
            logger.info(f"{OK} socker AF_INET6 SOCK_STREAM 9999")
    except SandBoxError:
        logger.error(f"{KO} socker AF_INET6 SOCK_STREAM 9999")
        rc = 1
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    # web connection
    import requests

    try:
        requests.get("http://www.google.com/")
        logger.info(f"{OK} get http://www.google.com")
    except SandBoxError:
        logger.error(f"{KO} get http://www.google.com")
        rc = 1
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    # udp connection ipv4
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(b"hello", ("127.0.0.1", 12345))
            logger.info(f"{OK} send DGRAM IPV4 to 12345 is accepted")

    except SandBoxError:
        logger.error(f"{KO} send DGRAM IPV4 to 12345 is denied")
        rc = 1
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(b"hello", ("127.0.0.1", 12346))
            logger.info(f"{OK} send DGRAM IPV4 to 12346 is accepted")
    except SandBoxError:  # type: ignore
        logger.error(f"{KO} send DGRAM IPV4 to 12346 is denied")
        rc = 1
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    # udp connection ipv6
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(b"hello", ("::1", 12345))
            logger.info(f"{OK} send DGRAM IPV6 to 12345 is accepted")
    except SandBoxError:
        logger.error(f"{KO} send DGRAM IPV6 to 12345 is denied")
        rc = 1
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    # udp bind ipv4
    try:
        with socket.socket(AF_INET, SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.bind(("localhost", 12345))
            logger.info(f"{OK} bind IPV4 to 12345 is accepted")
    except SandBoxError:
        logger.error(f"{KO} bind IPV4 to 12345 is denied")
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    # udp bind ipv6
    try:
        with socket.socket(AF_INET6, SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.bind(("::1", 9999))
            logger.info(f"{OK} bind IPV6 to 12345 is accepted")
    except SandBoxError:
        logger.error(f"{KO} bind IPV6 to 12345 is denied")
        rc = 1
    except TimeoutError as e:
        logger.error(f"{KO} socker AF_INET SOCK_STREAM 80 {e}")
        rc = 1

    # 2. Test denied access
    learning_mode = is_learning_mode()
    if "OS_SANDBOX" in os.environ:
        learning_mode = os.environ["OS_SANDBOX"].lower() == "none"
    if not learning_mode:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                remote_ip = socket.gethostbyname("www.github.com")
                sock.settimeout(timeout)
                sock.connect((remote_ip, 80))
            if learning_mode:
                logger.error(f"{KO} Must be stopped by pysandbox")
                rc = 1
        except SandBoxError:
            logger.info(f"{OK} Use socket to connect to github is stopped")
        except TimeoutError:
            logger.info(f"{OK} Use socket to connect to github is stopped by OS")

        try:
            with socket.socket(AF_INET, SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.bind(("127.0.0.1", 9998))
            if learning_mode:
                logger.error(f"{KO} Use bind IPv4 to 9998 be stopped by pysandbox")
                rc = 1
        except SandBoxError:
            logger.info(f"{OK}  Use bind IPv4 to 9998 is stopped")
        except TimeoutError:
            logger.info(f"{OK}  Use bind IPv4 to 9998 is stopped by OS")

        try:
            with socket.socket(AF_INET6, SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.bind(("::1", 9998))
            if learning_mode:
                logger.error(f"{KO} Use bind IPv6 to 9998 must be stopped by pysandbox")
                rc = 1
        except SandBoxError:
            logger.info(f"{OK} Use bind IPv6 to 9998 is stopped")
        except TimeoutError:
            logger.info(f"{OK} Use bind IPv6 to 9998 is stopped by OS")

    logger.info(f"{OK} Test Network")
    return rc


def _test_files() -> int:
    learning_mode = is_learning_mode()
    rc = 0

    # 1. Learn and accept
    try:
        with io.open("tmp/test.remove", "w") as _:
            pass
        logger.info(f"{OK} write to tmp/test.remove is accepted")
    except SandBoxError:  # type: ignore
        logger.error(f"{KO} write to tmp/test.remove is denied")
        rc = 1
    except OSError:
        logger.error(f"{KO} write to tmp/test.remove is denied")
        rc = 1

    # 2. Test denied access
    learning_mode = is_learning_mode()
    if "OS_SANDBOX" in os.environ:
        learning_mode = os.environ["OS_SANDBOX"].lower() == "none"
    if not learning_mode:
        # Check access refused
        try:
            with io.open("hack.py", "w"):
                pass
            if learning_mode:
                logger.error(f"{KO} Must be stopped by pysandbox")
                rc = 1
        except SandBoxError:
            logger.info(f"{OK} Write to hack.py is stopped")
        except OSError:
            logger.info(f"{OK} Write to hack.py is stopped by OS")

        try:
            with tempfile.TemporaryFile(mode="w+") as _:
                pass
            if learning_mode:
                logger.error(f"{KO} Must be stopped by pysandbox")
                rc = 1
        except SandBoxError:
            logger.info(f"{OK} Write to TemporaryFile is stopped")
        except OSError:
            logger.info(f"{OK} Write to TemporaryFile is stopped by OS")

        try:
            with tempfile.NamedTemporaryFile(mode="w+", delete=True) as _:
                pass
            if learning_mode:
                logger.error(f"{KO} Must be stopped by pysandbox")
                rc = 1
        except SandBoxError:
            logger.info(f"{OK} Write to NamedTemporaryFile is stopped")
        except OSError:
            logger.info(f"{OK} Write to NamedTemporaryFile is stopped by OS")

    try:
        with io.open(".env", "r") as f:
            s = f.read()
            if s:
                logger.error(f"{KO} .env must not be accessible")
                rc = 1
    except FileNotFoundError as e:
        # .env absent or not visible in sandbox (e.g. ignore=.env) → OK
        logger.info(f"{OK} .env not readable: file not found ({e})")
    except PermissionError as e:
        logger.info(f"{OK} read .env is stopped by OS ({e})")
    except OSError as e:
        logger.info(f"{OK} read .env is stopped by OS ({e})")
    logger.info(f"{OK} Test File")
    return rc


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


async def arun() -> tuple[int, int]:
    rc, error = await arun_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    logger.info(f"{OK} arun()")
    return rc, error


def run() -> tuple[int, int]:
    rc, error = run_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    logger.info(f"{OK} run()")
    return rc, error


@sandbox
def _call_llm(token: str) -> None:
    logger.info(f"{token=}")


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
            _, error = await arun()
            # logger.info("async_main.kill...")
            # os.kill(os.getpid(), signal.SIGTERM)
            # logger.info("async_main.kill... done")
            # await asyncio.sleep(5)  # The signal may be catch

    logger.info(f"{OK} async_main.return 0")
    return error


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
            _, error = run()
            logger.info(f"{OK} sync_main.run()")
            # logger.info("sync_main.kill...")
            # os.kill(os.getpid(), signal.SIGTERM)
            # logger.info("sync_main.kill done")

    return error


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


def test_raw_dns(server: str = "8.8.8.8") -> None:
    import socket

    logger.info(f"Testing raw UDP connection to {server}:53...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    try:
        # On n'envoie rien, on teste juste si le port est atteignable
        sock.connect((server, 53))
        logger.info("Successfully connected (UDP port reachable).")
    except Exception as e:
        logger.error(f"Connection failed: {e}")
    finally:
        sock.close()


if __name__ == "__main__":
    init_log_level()
    rc = 0
    rc += sync_main(sys.argv)
    # FIXME
    # logger.info("-------------------------")
    # rc += asyncio.run(async_main(sys.argv))
    # logger.info("End of __main__")
    sys.exit(rc)
