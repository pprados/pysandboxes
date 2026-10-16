# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`python_in_sb`: how the arguments of `python-sb` pick what runs, with every runner recorded."""

import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote import python_in_sb as pis


class _Runs:
    """Records what the dispatcher started, and what it saved at the end."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.learning = False
        self.saved = 0
        self.argv_seen: list[list[str]] = []
        self.returns: dict[str, int] = {"module": 0, "script": 0, "command": 0}

    def _record(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.calls.append((name, args, kwargs))
        self.argv_seen.append(list(sys.argv))

    def interactive(self, *args: Any, **kwargs: Any) -> None:
        self._record("interactive", args, kwargs)

    def module(self, *args: Any, **kwargs: Any) -> int:
        self._record("module", args, kwargs)
        return self.returns["module"]

    def script(self, *args: Any, **kwargs: Any) -> int:
        self._record("script", args, kwargs)
        return self.returns["script"]

    def command(self, *args: Any, **kwargs: Any) -> int:
        self._record("command", args, kwargs)
        return self.returns["command"]


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> _Runs:
    recorder = _Runs()
    monkeypatch.setattr(pis, "_python_interactive", recorder.interactive)
    monkeypatch.setattr(pis, "_python_module", recorder.module)
    monkeypatch.setattr(pis, "_python_script", recorder.script)
    monkeypatch.setattr(pis, "_python_command", recorder.command)
    monkeypatch.setattr(pis, "set_learning_path", lambda path: recorder.calls.append(("learning_path", (path,), {})))
    monkeypatch.setattr(pis, "set_learning_mode", lambda on: recorder.calls.append(("learning_mode", (on,), {})))
    monkeypatch.setattr(pis, "is_learning_mode", lambda: recorder.learning)

    def save() -> None:
        recorder.saved += 1

    monkeypatch.setattr(pis, "generate_config_from_learning", save)
    monkeypatch.setattr(sys, "argv", ["python-sb"])
    return recorder


def _run(runs: _Runs, argv: list[str], rules: Any = EmptyRules) -> int:
    return pis.python_in_sb(rules, argv)


def _names(runs: _Runs) -> list[str]:
    return [name for name, _, _ in runs.calls if not name.startswith("learning_")]


class TestInteractive:
    def test_no_argument_opens_the_banner_console(self, runs: _Runs) -> None:
        assert _run(runs, []) == 0

        ((name, args, _),) = [c for c in runs.calls if c[0] == "interactive"]
        assert args == (EmptyRules, True)

    def test_the_learning_state_is_set_from_the_rules_before_anything_runs(self, runs: _Runs) -> None:
        rules = EmptyRules._replace(learn=True, learning_path=Path("learned.profile"))

        _run(runs, [], rules)

        assert runs.calls[0] == ("learning_path", (Path("learned.profile"),), {})
        assert runs.calls[1] == ("learning_mode", (True,), {})


class TestModule:
    def _spec(self, monkeypatch: pytest.MonkeyPatch, origin: Any, found: bool = True) -> None:
        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name: SimpleNamespace(origin=origin, submodule_search_locations=None) if found else None,
        )

    def test_the_module_runs_with_its_origin_and_the_remaining_arguments_as_argv(
        self, runs: _Runs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._spec(monkeypatch, "/lib/mod.py")
        runs.returns["module"] = 7

        assert _run(runs, ["-m", "mod", "a", "b"]) == 7

        ((name, args, _),) = [c for c in runs.calls if c[0] == "module"]
        assert args == (EmptyRules, "mod")
        assert runs.argv_seen[-1] == ["/lib/mod.py", "a", "b"]

    def test_an_unknown_module_is_refused_like_python_dash_m(
        self, runs: _Runs, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._spec(monkeypatch, None, found=False)

        assert _run(runs, ["-m", "nowhere", "x"]) == 1

        assert f"{sys.executable}: No module named nowhere\n" == capsys.readouterr().err
        assert [c for c in runs.calls if c[0] == "module"] == []

    def test_a_package_without_main_is_refused_like_python_dash_m(
        self, runs: _Runs, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name: (
                SimpleNamespace(origin="/lib/pkg/__init__.py", submodule_search_locations=["/lib/pkg"])
                if name == "pkg"
                else None
            ),
        )

        assert _run(runs, ["-m", "pkg"]) == 1

        assert capsys.readouterr().err == (
            f"{sys.executable}: No module named pkg.__main__; 'pkg' is a package and cannot be directly executed\n"
        )

    def test_pytest_is_asked_for_colour(self, runs: _Runs, monkeypatch: pytest.MonkeyPatch) -> None:
        self._spec(monkeypatch, "/lib/pytest/__main__.py")

        _run(runs, ["-m", "pytest", "-q"])

        assert runs.argv_seen[-1] == ["/lib/pytest/__main__.py", "--color=yes", "-q"]

    @pytest.mark.parametrize("option", ["--color=no", "--color=auto"])
    def test_a_colour_choice_of_the_caller_is_kept(
        self, runs: _Runs, monkeypatch: pytest.MonkeyPatch, option: str
    ) -> None:
        self._spec(monkeypatch, "/lib/pytest/__main__.py")

        _run(runs, ["-m", "pytest", "-q", option])

        assert runs.argv_seen[-1] == ["/lib/pytest/__main__.py", "-q", option]

    @pytest.mark.parametrize("name", ["zzmod", "pytest_plugin", "pytests"])
    def test_a_module_that_only_sorts_after_pytest_gets_no_colour_option(
        self, runs: _Runs, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        self._spec(monkeypatch, f"/lib/{name}.py")

        _run(runs, ["-m", name, "-q"])

        assert runs.argv_seen[-1] == [f"/lib/{name}.py", "-q"]

    def test_a_module_flag_alone_explains_what_is_missing_and_runs_nothing(
        self, runs: _Runs, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(runs, ["-m"]) == 0

        err = capsys.readouterr().err
        assert err.startswith("Argument expected for -m option\n")
        assert "usage: python-sb [option] ... [-c cmd | -m mod | file | -] [arg] ..." in err
        assert "Try `python-sb -h' for more information." in err
        assert _names(runs) == []


class TestCommand:
    def test_the_command_body_runs_with_the_arguments_that_follow_it(self, runs: _Runs) -> None:
        runs.returns["command"] = 4

        assert _run(runs, ["-c", "print(1)", "a", "b"]) == 4

        ((_, args, _),) = [c for c in runs.calls if c[0] == "command"]
        assert args == (EmptyRules, "print(1)", ["-c", "a", "b"])

    def test_a_command_flag_alone_explains_what_is_missing_and_runs_nothing(
        self, runs: _Runs, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(runs, ["-c"]) == 0

        err = capsys.readouterr().err
        assert err.startswith("Argument expected for -c option\n")
        assert "usage: python-sb [option] ... [-c cmd | -m mod | file | -] [arg] ..." in err
        assert _names(runs) == []

    def test_a_dash_runs_the_program_read_from_standard_input(
        self, runs: _Runs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("print('from stdin')"))
        runs.returns["command"] = 5

        assert _run(runs, ["-", "arg"]) == 5

        ((_, args, _),) = [c for c in runs.calls if c[0] == "command"]
        assert args == (EmptyRules, "print('from stdin')", ["-", "arg"], "<stdin>")


class TestScript:
    def test_a_file_runs_as_a_script_with_its_own_arguments(self, runs: _Runs) -> None:
        runs.returns["script"] = 3

        assert _run(runs, ["tool.py", "a", "b"]) == 3

        ((_, args, _),) = [c for c in runs.calls if c[0] == "script"]
        assert args == (EmptyRules, Path("tool.py"), ["a", "b"])

    def test_only_the_dash_forms_are_options(self, runs: _Runs) -> None:
        _run(runs, ["-mod.py"])

        assert _names(runs) == ["script"]


class TestLearningSave:
    def test_a_learning_run_saves_what_it_learned(self, runs: _Runs) -> None:
        runs.learning = True

        _run(runs, ["tool.py"])

        assert runs.saved == 1

    def test_a_run_that_does_not_learn_saves_nothing(self, runs: _Runs) -> None:
        _run(runs, ["tool.py"])

        assert runs.saved == 0


def test_a_module_runs_as_the_main_module_like_python_dash_m(monkeypatch: pytest.MonkeyPatch) -> None:
    """``alter_sys`` makes the module ``sys.modules["__main__"]``: calendar publishes its enum members there."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(pis, "_before_user_code", lambda: None)
    monkeypatch.setattr(pis.runpy, "run_module", lambda name, **kwargs: seen.update(name=name, **kwargs))
    monkeypatch.setattr(pis.sys, "flags", SimpleNamespace(inspect=0))

    assert pis._python_module(EmptyRules, "calendar") == 0

    assert seen == {"name": "calendar", "run_name": "__main__", "alter_sys": True}
