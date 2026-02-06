import asyncio
import io
import logging
import os
import tempfile
from functools import partial
from socket import AF_INET, SOCK_STREAM, AF_INET6, SOCK_DGRAM

import pysandboxes
from pysandboxes import sandbox, sandboxes, SandBoxError

# FIXME dotenv.load_dotenv()

logger = logging.getLogger(__name__)


def init_log_level():
    if True: # TODO "PYTEST_RUN_CONFIG" in os.environ:
        format = '%(levelname)-5s [%(process)d] %(name)s: %(message)s'
    else:
        format = '%(asctime)s %(levelname)-5s [%(process)d] %(name)s: %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=format
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp_sse_client.client").setLevel(logging.WARNING)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(logging.INFO)


@sandbox
async def arun_in_sandbox():
    logger.info("Run 'arun_in_sandbox()' in sandbox")
    print(42)
    return 42


@sandbox
def run_in_sandbox():
    logger.info("Run 'run_in_sandbox()' in sandbox")

    # tcp connexion
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        remote_ip = socket.gethostbyname("www.google.com")
        xx=socket.gethostbyname_ex("www.google.com")
        addr_infos = socket.getaddrinfo("www.google.com",None,family=socket.AF_UNSPEC)
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

    # udp connexion ipv6
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"hello", ("::1", 12345))

    # udp bind ipv4
    with socket.socket(AF_INET, SOCK_DGRAM) as sock:
        sock.bind(("localhost", 12345))

    # udp bind ipv6
    with socket.socket(AF_INET6, SOCK_STREAM) as sock:
        sock.bind(("::1", 0))

    # ---------- File

    # with open("README.md", "r"):
    #     pass
    # os.path.exists("./README.md")

    # assert pathlib.Path("README.md").is_file()
    # pathlib.Path("README.md").read_text()

    try:
        with io.open("tmp/test.remove", "w") as f:
            pass
        # assert is_learning_mode() or False, "Must be stopped by pysandbox"
    except SandBoxError as e:
        print(e)


    try:
        with io.open("tst_wasm/factorial.wasm", "r") as f:
            pass
        # assert is_learning_mode() or False, "Must be stopped by pysandbox"
    except SandBoxError as e:
        print(e)

    try:
        with io.open("pysandboxes/__init__.py", "r") as f:
            pass
        # assert is_learning_mode() or False, "Must be stopped by pysandbox"
    except SandBoxError as e:
        print(e)

    if "PYENV_ROOT" in os.environ:
        try:
            os.listdir(os.environ.get("PYENV_ROOT"))
            # assert is_learning_mode() or False, "Must be stopped by pysandbox"
        except SandBoxError as e:
            print(e)

    if "VIRTUAL_ENV" in os.environ:
        try:
            os.listdir(os.environ.get("VIRTUAL_ENV"))
            # assert is_learning_mode() or False, "Must be stopped by pysandbox"
        except SandBoxError as e:
            print(e)

    assert os.environ["HOME"]

    with os.scandir("docs") as entries:
        for entry in entries:
            print(entry.name)

    try:
        with tempfile.TemporaryFile(mode='w+') as temp_file:
            pass
    except SandBoxError as e:
        print(e)

    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=True) as temp_file:
            pass
    except SandBoxError as e:
        print(e)

    print(42)
    return 42


async def ainit_sandbox():
    logger.error("INIT Daemon")


async def async_manager():
    for i in range(0, 2):
        async with sandboxes(init_fn=init_sandbox):
            assert await arun() == 42


# %% --------------------------------------
def init_sandbox():
    logger.debug("INIT Daemon")
    init_log_level()

async def async_init_sandbox():
    await asyncio.sleep(0)
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

def main():
    init_log_level()
    os.environ["LLM_TOKEN"]="abc"


    for i in range(0, 1):
        # asyncio.run(async_manager())
        # # print("----------------")
        with sandboxes(async_init_sandbox):
            run()
        print("----------------")
        # pysandboxes.run(arun(),init_fn=init_sandbox)
        # print("----------------")
