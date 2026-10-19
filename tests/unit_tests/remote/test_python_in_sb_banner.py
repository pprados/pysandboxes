# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The REPL banner must not crash when the configuration file lies outside the working directory."""

import io
import signal
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pysandboxes.remote import python_in_sb


def test_banner_accepts_a_config_outside_the_working_directory(tmp_path: Path) -> None:
    rules = MagicMock(learn=False, use_py_sandbox=True, os_sandbox="subprocess")
    rules.learning_path = tmp_path / "outside" / ".py-sandboxes"
    banners: list[str] = []

    def _interact(banner: str, **_: Any) -> None:
        banners.append(banner)

    with (
        patch.object(python_in_sb, "_before_user_code"),
        patch.object(python_in_sb, "is_learning_mode", return_value=False),
        patch.object(python_in_sb, "is_allowed", return_value=False),
        patch.object(python_in_sb.code, "interact", _interact),
    ):
        assert python_in_sb._python_interactive(rules, True) == 0

    assert repr(str(rules.learning_path))[1:-1] in banners[0]


class _Tty(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _interact_with(
    monkeypatch: pytest.MonkeyPatch,
    rules: Any,
    *,
    tty: bool = False,
    term: str | None = None,
    learning: bool = False,
    allowed: bool = False,
    ipython: bool = False,
) -> dict[str, Any]:
    """Run the REPL entry with `code.interact` recorded, and IPython either missing or refused."""
    seen: dict[str, Any] = {}

    def interact(banner: str, **kwargs: Any) -> None:
        seen["banner"] = banner
        seen.update(kwargs)

    if term is None:
        monkeypatch.delenv("TERM", raising=False)
    else:
        monkeypatch.setenv("TERM", term)
    monkeypatch.setitem(sys.modules, "__main__", sys.modules["__main__"])
    if not ipython:
        monkeypatch.setitem(sys.modules, "IPython", None)
    monkeypatch.setattr(python_in_sb.sys, "stdout", _Tty(tty))
    monkeypatch.setattr(python_in_sb, "_before_user_code", lambda: None)
    monkeypatch.setattr(python_in_sb, "is_learning_mode", lambda: learning)
    monkeypatch.setattr(python_in_sb, "is_allowed", lambda door: allowed)
    monkeypatch.setattr(python_in_sb.code, "interact", interact)

    assert python_in_sb._python_interactive(rules, True) == 0
    return seen


def _rules(tmp_path: Path, **overrides: Any) -> Any:
    values: dict[str, Any] = {"learn": False, "use_py_sandbox": True, "os_sandbox": "subprocess"}
    values.update(overrides)
    rules = MagicMock(**values)
    rules.learning_path = tmp_path / ".py-sandboxes"
    return rules


@pytest.mark.parametrize(
    ("tty", "term", "coloured"),
    [(True, "xterm-256color", True), (True, "dumb", False), (False, "xterm-256color", False), (True, None, False)],
)
def test_the_banner_is_coloured_only_on_a_colour_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tty: bool, term: str | None, coloured: bool
) -> None:
    seen = _interact_with(monkeypatch, _rules(tmp_path), tty=tty, term=term)

    assert ("\033[1m" in seen["banner"]) is coloured
    assert ("*** " in seen["banner"]) is not coloured


def test_a_learning_run_says_what_it_saves_and_where(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rules = _rules(tmp_path, learn=True)

    seen = _interact_with(monkeypatch, rules)

    assert "LEARNED" in seen["banner"]
    assert seen["exitmsg"] == f"Save rules to {str(rules.learning_path)!r}"


@pytest.mark.parametrize(
    ("overrides", "fragment", "present"),
    [
        ({"os_sandbox": "bwrap"}, "os-sandbox='bwrap'", True),
        ({"os_sandbox": "unshare"}, "os-sandbox='unshare'", True),
        ({"os_sandbox": "subprocess"}, "os-sandbox", False),
        ({"use_py_sandbox": False, "os_sandbox": "bwrap"}, "LIMITED only by the os-sandbox of type 'bwrap'", True),
        ({}, "LIMITED according to the rules", True),
    ],
)
def test_the_banner_names_the_layers_that_limit_the_apis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, overrides: dict[str, Any], fragment: str, present: bool
) -> None:
    seen = _interact_with(monkeypatch, _rules(tmp_path, **overrides))

    assert (fragment in seen["banner"]) is present
    assert seen["exitmsg"] is None


def test_the_standard_console_leaves_on_exit_only_from_python_3_13(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _interact_with(monkeypatch, _rules(tmp_path))

    assert seen.get("local_exit") is (True if sys.version_info[:2] >= (3, 13) else None)


def test_a_refused_threads_door_falls_back_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _interact_with(monkeypatch, _rules(tmp_path), allowed=False)

    err = capsys.readouterr().err
    assert "Falling back to the standard Python REPL" in err
    assert "Traceback" not in err


def test_a_missing_ipython_falls_back_with_its_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _interact_with(monkeypatch, _rules(tmp_path), allowed=True)

    err = capsys.readouterr().err
    assert "ModuleNotFoundError" in err
    assert "Falling back" not in err


def test_termination_signals_are_caught_to_save_the_learned_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[int] = []
    monkeypatch.setattr(python_in_sb.signal, "signal", lambda signum, handler: installed.append(signum))

    python_in_sb._register_signals_handlers()

    assert {signal.SIGINT, signal.SIGTERM} <= set(installed)
