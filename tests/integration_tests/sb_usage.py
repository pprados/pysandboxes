import io
import logging
import os
import tempfile
from pathlib import Path
from socket import AF_INET, AF_INET6, SOCK_DGRAM, SOCK_STREAM
from typing import Any, List, Mapping, cast

from pysandboxes import SandBoxError, sandbox, sandboxes
from pysandboxes.learning import is_learning_mode
from pysandboxes.remote.python_in_sb import convert_extra_rules

logger = logging.getLogger(__name__)


def init_log_level() -> None:
    sandboxes_level = logging.DEBUG  # FIXME
    uvicorn_level = logging.WARNING
    logging.getLogger("asyncio").setLevel(uvicorn_level)
    logging.getLogger("uvicorn").setLevel(uvicorn_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_level)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandboxes_level)
    logging.getLogger().setLevel(sandboxes_level)  # Set the default level for root


@sandbox
async def arun_in_sandbox() -> int:
    text_wrapper = io.TextIOWrapper(
        io.BytesIO(b"Ceci est un test en fran\xc3\xa7ais."), encoding="utf8"  # FIXME
    )
    logger.info("Run 'arun_in_sandbox()' in sandbox")
    _test_envs()
    _test_files()
    _test_network()
    print(42)
    return 42


@sandbox
def run_in_sandbox() -> int:
    logger.info("Run 'run_in_sandbox()' in sandbox")

    _test_network()

    _test_files()

    _test_envs()

    print(42)
    return 42


def _test_envs() -> None:
    if "PYENV_ROOT" in os.environ:
        try:
            os.listdir(os.environ.get("PYENV_ROOT"))
            # assert is_learning_mode() or False, "Must be stopped by pysandbox"
        except FileNotFoundError:
            print("Error catch by os-sandbox")
        except SandBoxError:
            print("Error catch by pysandboxes")
    if "VIRTUAL_ENV" in os.environ:
        try:
            os.listdir(os.environ.get("VIRTUAL_ENV"))
            # assert is_learning_mode() or False, "Must be stopped by pysandbox"
        except SandBoxError as e:
            print(e)
    assert os.environ["LANGUAGE"]


def _test_network() -> None:
    # tcp connection
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        remote_ip = socket.gethostbyname("www.google.com")
        socket.gethostbyname_ex("www.google.com")
        socket.getaddrinfo("www.google.com", None, family=socket.AF_UNSPEC)
        sock.connect((remote_ip, 80))
    # tcp bind ipv4
    with socket.socket(AF_INET, SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
    # tcp bind ipv6
    with socket.socket(AF_INET6, SOCK_STREAM) as sock:
        sock.bind(("::1", 0))
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
        sock.bind(("::1", 0))


def _test_files() -> None:
    print("---- Test files")
    learning = is_learning_mode()
    try:
        with io.open("tmp/test.remove", "w") as _:
            pass
        # assert not learning, "Must be stopped by pysandbox"
    except Exception as e:
        logger.exception(e)
    except SandBoxError as e:
        if learning:
            logger.exception(e)

    try:
        with io.open("tst_wasm/factorial.wasm", "r"):
            pass
        logger.error("Must be stopped by pysandbox")
    except SandBoxError:
        assert not is_learning_mode()
    except Exception as e:
        logger.exception(e)

    try:
        with io.open("pysandboxes/__init__.py", "r"):
            pass
        # assert is_learning_mode() or False, "Must be stopped by pysandbox"
    except SandBoxError:
        assert not is_learning_mode()
    except Exception as e:
        logger.exception(e)

    print("---- Test scandir docs")
    use_alias_rule = False
    if use_alias_rule:
        data = "tests/alias"
    else:
        data = "tests/data"
    all_entries = []
    with os.scandir(data) as entries:
        all_entries = [entry.name for entry in entries]
    assert "data.txt" in all_entries

    try:
        with tempfile.TemporaryFile(mode="w+") as _:
            pass
    except SandBoxError:
        logger.exception("tempfile.TemporaryFile")
    except Exception:
        logger.exception("tempfile.TemporaryFile")

    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=True) as _:
            pass
    except SandBoxError:
        logger.exception("tempfile.NamedTemporaryFile")
    except Exception:
        logger.exception("tempfile.NamedTemporaryFile")


async def ainit_sandbox() -> None:
    logger.error("INIT Daemon")


async def async_manager() -> None:
    for i in range(0, 2):
        async with sandboxes(init_fn=init_sandbox):
            assert await arun() == 42


# %% --------------------------------------
def init_sandbox() -> None:
    logger.debug("INIT sandbox")
    init_log_level()


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
    # pysandboxes_config = Path("tests/test.py-sandboxes")
    config_path = Path(".py-sandboxes")
    if "learn" in extra_rules:
        learning_path, *_ = extra_rules.get("learn", set())
        if not learning_path:
            learning_path = ".py-sandboxes.test"
        extra_rules["learn"] = {learning_path}

    for i in range(0, 1):
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
