import logging
import os
import tempfile
import socket
from socket import AF_INET, SOCK_STREAM, SOCK_DGRAM, AF_INET6

import pysandboxes
from pysandboxes import sandbox, sandboxes
from pysandboxes.exception import SandBoxError

# FIXME dotenv.load_dotenv()

logger = logging.getLogger(__name__)

def init_log_level():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(levelname)-5s [%(process)d] %(name)s:%(message)s'
        # format = '%(asctime)s %(levelname)-5s [%(process)d] %(name)s:%(message)s'
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp_sse_client.client").setLevel(logging.WARNING)
    logging.getLogger("Pysandboxes").setLevel(logging.DEBUG)
    logging.getLogger("pysandboxes").setLevel(logging.DEBUG)



@sandbox
async def arun_in_sandbox():
    logger.info("Run 'arun_in_sandbox()' in sandbox")
    print(42)
    return 42


@sandbox
def run_in_sandbox():
    logger.info("Run 'run_in_sandbox()' in sandbox")


    # # tcp connexion
    # import socket
    # with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    #     remote_ip = socket.gethostbyname("www.google.com")
    #     xx=socket.gethostbyname_ex("www.google.com")
    #     addr_infos = socket.getaddrinfo("www.google.com",None,family=socket.AF_UNSPEC)
    #     sock.connect((remote_ip, 80))
    #
    # # tcp bind ipv4
    # with socket.socket(AF_INET, SOCK_STREAM) as sock:
    #     sock.bind(("localhost", 0))

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

    import io
    try:
        with io.open("test.remove", "w") as f:
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


def main():
    init_log_level()

    for i in range(0, 1):
        # asyncio.run(async_manager())
        # # print("----------------")
        with pysandboxes.sandboxes(init_sandbox):
            run()
        print("----------------")
        # pysandboxes.run(arun(),init_fn=init_sandbox)
        # print("----------------")
