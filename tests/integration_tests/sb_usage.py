import io
import logging
import os
import tempfile
from pathlib import Path
from pprint import pprint
from socket import AF_INET, SOCK_STREAM, AF_INET6, SOCK_DGRAM
from typing import Dict

from pysandboxes import sandbox, sandboxes, SandBoxError
from pysandboxes.learning import is_learning_mode
from pysandboxes.remote.python_in_sb import convert_extra_rules

logger = logging.getLogger(__name__)


def init_log_level():
    sandboxes_level = logging.WARNING
    uvicorn_level = logging.WARNING
    format = '[%(process)d] %(levelname)-5s %(name)s %(message)s'
    logging.basicConfig(
        level=min(sandboxes_level, logging.INFO),
        format=format
    )
    logging.getLogger("asyncio").setLevel(uvicorn_level)
    logging.getLogger("uvicorn").setLevel(uvicorn_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_level)
    logging.getLogger("Pysandboxes").setLevel(uvicorn_level)
    logging.getLogger("pysandboxes").setLevel(sandboxes_level)
    logger.setLevel(logging.INFO)


@sandbox
async def arun_in_sandbox():
    logger.info("Run 'arun_in_sandbox()' in sandbox")
    # FIXME _test_envs()
    _test_files()
    # _test_network()
    print(42)
    return 42


@sandbox
def run_in_sandbox():
    logger.info("Run 'run_in_sandbox()' in sandbox")

    _test_network()

    _test_files()

    _test_envs()

    print(42)
    return 42


def _test_envs():
    if "PYENV_ROOT" in os.environ:
        try:
            os.listdir(os.environ.get("PYENV_ROOT"))
            # assert is_learning_mode() or False, "Must be stopped by pysandbox"
        except FileNotFoundError as e:
            print("Error catch by os-sandbox")
        except SandBoxError as e:
            print("Error catch by pysandboxes")
    if "VIRTUAL_ENV" in os.environ:
        try:
            os.listdir(os.environ.get("VIRTUAL_ENV"))
            # assert is_learning_mode() or False, "Must be stopped by pysandbox"
        except SandBoxError as e:
            print(e)
    assert os.environ["HOME"]


def _test_network():
    # tcp connexion
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        remote_ip = socket.gethostbyname("www.google.com")
        xx = socket.gethostbyname_ex("www.google.com")
        addr_infos = socket.getaddrinfo("www.google.com", None, family=socket.AF_UNSPEC)
        sock.connect((remote_ip, 80))
    # tcp bind ipv4
    with socket.socket(AF_INET, SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
    # tcp bind ipv6
    with socket.socket(AF_INET6, SOCK_STREAM) as sock:
        sock.bind(("::1", 0))
    # web connexion
    import requests
    f = requests.get("http://www.google.com/")
    # udp connexion ipv4
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"hello", ("127.0.0.1", 12345))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"hello", ("127.0.0.1", 12346))
    # udp connexion ipv6
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"hello", ("::1", 12345))
    # udp bind ipv4
    with socket.socket(AF_INET, SOCK_DGRAM) as sock:
        sock.bind(("localhost", 12345))
    # udp bind ipv6
    with socket.socket(AF_INET6, SOCK_STREAM) as sock:
        sock.bind(("::1", 0))


def _test_files():
    print("---- Test files")
    learning = is_learning_mode()
    try:
        with io.open("tmp/test.remove", "w") as f:
            pass
        # assert not learning, "Must be stopped by pysandbox"
    except Exception as e:
        logger.exception(e)
    except SandBoxError as e:
        if learning:
            logger.exception(e)

    try:
        with io.open("tst_wasm/factorial.wasm", "r") as f:
            pass
        logger.error("Must be stopped by pysandbox")
    except SandBoxError as e:
        assert not is_learning_mode()
    except Exception as e:
        logger.exception(e)

    try:
        with io.open("pysandboxes/__init__.py", "r") as f:
            pass
        # assert is_learning_mode() or False, "Must be stopped by pysandbox"
    except SandBoxError as e:
        assert not is_learning_mode()
    except Exception as e:
        logger.exception(e)

    print("---- Test scandir docs")
    use_alias_rule = False
    if use_alias_rule:
        datas = "tests/alias"
    else:
        datas = "tests/data"
    all_entries = []
    with os.scandir(datas) as entries:
        all_entries = [entry.name for entry in entries]
    assert "data.txt" in all_entries

    try:
        with tempfile.TemporaryFile(mode='w+') as temp_file:
            pass
    except SandBoxError as e:
        logger.exception("tempfile.TemporaryFile")
    except Exception as e:
        logger.exception("tempfile.TemporaryFile")

    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=True) as temp_file:
            pass
    except SandBoxError as e:
        logger.exception("tempfile.NamedTemporaryFile")
    except Exception as e:
        logger.exception("tempfile.NamedTemporaryFile")


async def ainit_sandbox():
    logger.error("INIT Daemon")


async def async_manager():
    for i in range(0, 2):
        async with sandboxes(init_fn=init_sandbox):
            assert await arun() == 42


# %% --------------------------------------
def init_sandbox():
    logger.debug("INIT sandbox")
    init_log_level()


async def async_init_sandbox():
    init_sandbox()


async def arun():
    rc = await arun_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    return rc


def run():
    rc = run_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    return rc


@sandbox
def _call_llm(token: str):
    print(f"{token=}")


def call_llm():
    _call_llm(token=os.environ["USER"])


async def main(argv: Dict[str, str]) -> int:
    init_log_level()
    os.environ["LLM_TOKEN"] = "abc"

    # def audit_hook(event, args):
    #     logger.debug(f'Audit event: {event} {" XX ,".join(map(repr, args))}')
    # import sys
    # sys.addaudithook(audit_hook)

    extra_rules = convert_extra_rules(argv[1:])
    config_path = Path("tests/test.py-sandboxes")
    if "learn" in extra_rules:
        learning_path, *_ = extra_rules.get("learn", [''])
        if not learning_path:
            learning_path = ".py-sandboxes.test"
        extra_rules["learn"] = learning_path

    for i in range(0, 1):
        # asyncio.run(async_manager())
        # # # print("----------------")
        async with sandboxes(async_init_sandbox,
                             config_path=config_path,
                             # learn=".py-sandboxes", # Learn all the times
                             # os_sandbox="none",
                             **extra_rules
                             ):
            await arun()
        # TODO: voir la capture d'exception
        # print("----------------")
        # pysandboxes.run(arun(),init_fn=init_sandbox)
        # print("----------------")

# from pysandboxes.sandboxes_api import sandboxes
#
# def init_sandbox():
#     print("init")
#
# def main():
#     with sandboxes(init_fn=init_sandbox):
#         print("ok")
