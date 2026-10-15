# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""Integration tests for the subinterpreter provider: the guards hold in the subinterpreter, not in the host."""

import builtins
import logging
import os
import subprocess
from pathlib import Path
from typing import Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes import sandbox
from pysandboxes._os_sandbox import shutdown_daemon, start_daemon
from pysandboxes.e import RuleApiPermissionError, RuleFileNotFoundError
from pysandboxes.lifecycle import is_armed, is_in_sandbox
from pysandboxes.py_sandbox import load_and_parse_config


@pytest.fixture(scope="module", autouse=True)
def start_daemon_for_tests() -> Iterator[None]:
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    all_rules = load_and_parse_config(config_path=config_path)._replace(os_sandbox="subinterpreter")
    start_daemon(all_rules, envs=os.environ, log_level=logging.root.getEffectiveLevel(), init_fn=None)
    yield
    shutdown_daemon(graceful_shutdown=False)


@sandbox()
def sync_function(a: str, b: str) -> str:
    return f"{a} {b}"


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio

    await asyncio.sleep(0)
    return f"{a} {b}"


@sandbox()
def raise_value_error() -> None:
    raise ValueError("raised in the subinterpreter")


@sandbox()
def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()


@sandbox()
def run_shell() -> int:
    return os.system("true")


@sandbox()
def big_result(size: int) -> bytes:
    return b"x" * size


def test_sync_function() -> None:
    assert sync_function("a", b="b") == "a b"


async def test_async_function() -> None:
    assert await async_function("a", b="b") == "a b"


def test_exception_crosses_back() -> None:
    with pytest.raises(ValueError, match="raised in the subinterpreter"):
        raise_value_error()


def test_file_outside_the_rules_is_denied() -> None:
    with pytest.raises(RuleFileNotFoundError):
        read_file("/etc/hostname")


def test_sensitive_call_is_denied() -> None:
    with pytest.raises(RuleApiPermissionError):
        run_shell()


def test_result_larger_than_the_pipe_buffer() -> None:
    # 64 KiB of pipe buffer, below the 384 KiB the transport guard admits.
    assert len(big_result(200_000)) == 200_000


def test_the_host_stays_unpatched() -> None:
    """The guards are armed in the subinterpreter only: the host keeps its own builtins and state."""
    sync_function("a", "b")
    assert not is_in_sandbox()
    assert not is_armed()
    assert not getattr(os.system, "__pysandbox_api__", False)
    assert builtins.open("/etc/hostname").read() == Path("/etc/hostname").read_text()


@sandbox()
def environ_keys() -> list[str]:
    return sorted(os.environ)


@sandbox()
def environ_routes() -> dict[str, bool]:
    import importlib
    import posix
    import sys

    routes = {
        "import posix": b"HOME" in posix.environ,
        "import_module": b"HOME" in importlib.import_module("posix").environ,
    }
    for name in ("os", "posix"):
        sys.modules.pop(name, None)
    routes["fresh os"] = "HOME" in importlib.import_module("os").environ
    return routes


@pytest.mark.xfail(
    strict=True,
    reason="a fresh `posix` module rebuilds environ from the process environment, which is the host's: "
    "the env= rules do not hold against pure Python code under this provider",
)
def test_no_python_route_rebuilds_the_host_environment() -> None:
    """The process environment is the host's: no re-import may rebuild the full mapping from it."""
    assert environ_routes() == {"import posix": False, "import_module": False, "fresh os": False}


def test_the_environment_is_narrowed_in_the_subinterpreter_only() -> None:
    """The subinterpreter sees the profile's variables; the host's process environment loses none."""
    assert "HOME" not in environ_keys()
    assert "HOME" in os.environ
    assert subprocess.run(["printenv", "HOME"], capture_output=True, text=True).stdout.strip() == os.environ["HOME"]
