# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import builtins
import importlib
import io
import pkgutil
import socket
import sys
from typing import Any, Callable, Iterator

import deal
import pytest  # type: ignore[import-untyped]

import pysandboxes
from pysandboxes._contracts import HAS_DEAL, pre

CONTRACT_ATTR = "__deal_contract"


def _decorated() -> Callable[[int], int]:
    @pre(lambda x: x >= 0)
    def f(x: int) -> int:
        return x

    return f


def _pysandboxes_callables() -> Iterator[tuple[str, Any]]:
    for info in pkgutil.walk_packages(pysandboxes.__path__, "pysandboxes."):
        if info.name.rsplit(".", 1)[-1] in {"python_sb", "__main__"} or ".templates" in info.name:
            continue
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if callable(value):
                yield f"{info.name}.{name}", value


def test_the_detectors_see_a_decorated_function() -> None:
    """Negative control of every check below: a contract leaves both a marker and a `__wrapped__`."""
    assert HAS_DEAL
    func = _decorated()
    assert hasattr(func, CONTRACT_ATTR)
    assert hasattr(func, "__wrapped__")


def test_a_has_contract_is_detected() -> None:
    @deal.has("io")
    def f() -> None: ...

    assert getattr(f, CONTRACT_ATTR).patcher is not None


def test_deal_never_replaces_the_path_finder() -> None:
    assert not any(
        type(finder).__name__ == "DealFinder" or getattr(finder, "__name__", "") == "DealFinder"
        for finder in sys.meta_path
    )


def test_no_pysandboxes_function_carries_a_has_contract() -> None:
    offenders = [
        qualname
        for qualname, value in _pysandboxes_callables()
        if getattr(getattr(value, CONTRACT_ATTR, None), "patcher", None) is not None
    ]
    assert offenders == []


@pytest.mark.parametrize(
    "owner, name",
    [
        (builtins, "open"),
        (builtins, "eval"),
        (builtins, "exec"),
        (builtins, "compile"),
        (builtins, "__import__"),
        (io, "open"),
        (socket, "socket"),
    ],
)
def test_a_function_a_guard_replaces_has_no_contract_and_no_wrapped(owner: Any, name: str) -> None:
    target = getattr(owner, name)
    assert not hasattr(target, CONTRACT_ATTR)
    assert not hasattr(target, "__wrapped__")


def test_contracts_are_off_for_a_process_that_never_enables_deal() -> None:
    """`_contracts` disables deal on import: a fresh interpreter must not enforce anything."""
    import subprocess

    code = (
        "import pysandboxes._contracts as c, deal\n"
        "@c.pre(lambda x: x > 0)\n"
        "def f(x): return x\n"
        "assert f(-1) == -1\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
