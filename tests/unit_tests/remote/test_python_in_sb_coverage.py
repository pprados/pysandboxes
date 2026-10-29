# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The package loading, the debug logging and the signal handler of `python-sb` that the other tests leave out."""

import importlib.machinery
import importlib.util
import logging
import signal
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pysandboxes.remote import python_in_sb


@pytest.fixture
def package(tmp_path: Path) -> Iterator[tuple[importlib.machinery.ModuleSpec, str]]:
    """A package on disk, not imported; whatever the test leaves in sys.modules is removed."""
    root = tmp_path / "sbpkg_cov"
    root.mkdir()
    init = root / "__init__.py"
    init.write_text("VALUE = 7\n")
    spec = importlib.util.spec_from_file_location("sbpkg_cov", init, submodule_search_locations=[str(root)])
    assert spec is not None
    yield spec, "sbpkg_cov"
    sys.modules.pop("sbpkg_cov", None)


def test_a_package_is_judged_executed_and_registered(package: tuple[importlib.machinery.ModuleSpec, str]) -> None:
    spec, name = package
    with patch.object(python_in_sb, "_judge_user_import") as judge:
        python_in_sb._load_module_packages([spec])

    judge.assert_called_once_with(name)
    assert sys.modules[name].VALUE == 7  # type: ignore[attr-defined]


def test_a_package_already_loaded_is_left_alone(package: tuple[importlib.machinery.ModuleSpec, str]) -> None:
    spec, name = package
    already = Mock()
    sys.modules[name] = already
    with patch.object(python_in_sb, "_judge_user_import") as judge:
        python_in_sb._load_module_packages([spec])

    judge.assert_not_called()
    assert sys.modules[name] is already


def test_a_package_that_fails_to_execute_is_forgotten_and_the_error_propagates(tmp_path: Path) -> None:
    root = tmp_path / "sbpkg_broken"
    root.mkdir()
    (root / "__init__.py").write_text("raise RuntimeError('broken package')\n")
    spec = importlib.util.spec_from_file_location(
        "sbpkg_broken", root / "__init__.py", submodule_search_locations=[str(root)]
    )
    assert spec is not None
    with patch.object(python_in_sb, "_judge_user_import"), pytest.raises(RuntimeError, match="broken package"):
        python_in_sb._load_module_packages([spec])

    assert "sbpkg_broken" not in sys.modules


def test_a_submodule_is_set_on_its_parent_package(tmp_path: Path) -> None:
    parent = Mock()
    sys.modules["sbpkg_parent"] = parent
    try:
        (tmp_path / "child.py").write_text("X = 1\n")
        spec = importlib.util.spec_from_file_location("sbpkg_parent.child", tmp_path / "child.py")
        assert spec is not None
        with patch.object(python_in_sb, "_judge_user_import"):
            python_in_sb._load_module_packages([spec])

        assert parent.child is sys.modules["sbpkg_parent.child"]
    finally:
        sys.modules.pop("sbpkg_parent", None)
        sys.modules.pop("sbpkg_parent.child", None)


@pytest.fixture
def restored_loggers() -> Iterator[None]:
    names = ["asyncio", "uvicorn", "uvicorn.error", "aiohttp_sse_client.client", "Pysandboxes", "pysandboxes"]
    names += ["pysandboxes.guard_import", "pysandboxes.remote.firejail_daemon"]
    levels = {n: logging.getLogger(n).level for n in names}
    yield
    for n, level in levels.items():
        logging.getLogger(n).setLevel(level)


def test_the_debug_log_opens_the_sandbox_and_quiets_the_noisy_libraries(restored_loggers: None) -> None:
    with patch.object(python_in_sb, "config_log") as config:
        python_in_sb._debug_log()

    config.assert_called_once_with(logging.DEBUG)
    assert logging.getLogger("pysandboxes").level == logging.DEBUG
    assert logging.getLogger("pysandboxes.guard_import").level == logging.INFO
    assert logging.getLogger("uvicorn").level == logging.ERROR


def _handlers(previous: Any) -> tuple[Any, Mock]:
    install = Mock()
    with patch.object(python_in_sb.signal, "getsignal", return_value=previous):
        with patch.object(python_in_sb.signal, "signal", install):
            python_in_sb._register_signals_handlers()
    handler = next(c.args[1] for c in install.call_args_list if c.args[0] == signal.SIGTERM)
    return handler, install


def test_the_signal_handler_saves_the_learning_once_and_delegates() -> None:
    previous = Mock(return_value="done")
    handler, install = _handlers(previous)
    with patch.object(python_in_sb, "generate_config_from_learning") as save:
        assert handler(signal.SIGTERM, None) == "done"
        assert handler(signal.SIGTERM, None) == "done"

    save.assert_called_once_with()
    assert previous.call_count == 2
    assert {c.args[0] for c in install.call_args_list} >= {signal.SIGINT, signal.SIGTERM}


def test_a_signal_with_a_default_disposition_only_saves_the_learning() -> None:
    handler, _ = _handlers(signal.SIG_DFL)
    with patch.object(python_in_sb, "generate_config_from_learning") as save:
        assert handler(signal.SIGTERM, None) is None

    save.assert_called_once_with()


def test_a_module_nobody_finds_has_no_spec() -> None:
    assert python_in_sb._find_one_module_spec("no_such_module_for_sure", None) is None
    assert python_in_sb._find_module_specs("no_such_module_for_sure") == python_in_sb._ModuleSpecs((), None, None)


def test_a_dotted_name_below_a_plain_module_has_no_spec() -> None:
    """`os` is a module, not a package: nothing can be looked up below it."""
    assert python_in_sb._find_module_specs("os.path") == python_in_sb._ModuleSpecs((), None, None)


def test_a_missing_submodule_of_a_real_package_keeps_the_packages_found_so_far() -> None:
    specs = python_in_sb._find_module_specs("json.no_such_submodule")

    assert specs.module is None and specs.main is None
    assert [s.name for s in specs.packages] == ["json"]


# %% The REPL through IPython, and the fall back to the plain one


def test_ipython_is_started_with_the_sandbox_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import IPython

    from .test_python_in_sb_banner import _interact_with, _rules

    start = Mock()
    monkeypatch.setattr(IPython, "start_ipython", start)

    seen = _interact_with(monkeypatch, _rules(tmp_path), ipython=True, allowed=True)

    start.assert_called_once()
    assert start.call_args.kwargs["config"].TerminalInteractiveShell.prompts_class.__name__ == "CustomPrompts"
    assert seen == {}
    assert "IPython" in sys.stdout.getvalue()  # type: ignore[union-attr]


def test_a_broken_ipython_is_reported_and_the_plain_repl_takes_over(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    import IPython

    from .test_python_in_sb_banner import _interact_with, _rules

    def broken(**kwargs: Any) -> None:
        raise ImportError("IPython cannot start")

    monkeypatch.setattr(IPython, "start_ipython", broken)
    monkeypatch.setattr(python_in_sb.sys, "ps1", ">>> ", raising=False)

    seen = _interact_with(monkeypatch, _rules(tmp_path), ipython=True, allowed=True)

    assert "IPython cannot start" in capsys.readouterr().err
    assert "exitmsg" in seen
    assert python_in_sb.sys.ps1 == "⚠ >>> "
