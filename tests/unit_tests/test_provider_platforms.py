# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Each provider declares the platforms it runs on, and nothing starts it elsewhere.

The tag lives in the registry so it can be read without importing the provider: a
provider's module may depend on what another platform lacks.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest  # type: ignore[import-untyped]

from pysandboxes import _os_sandbox
from pysandboxes.all_rules import AllRules
from pysandboxes.guard_provider import parse_rules
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.sb_types import ConfigLine


@pytest.fixture
def landlock_rules(tmp_path: Path) -> AllRules:
    # Parsed as `none`, then renamed: parsing `landlock` loads its provider class, and
    # a patched sys.platform does not give a Windows runner what that module may need.
    profile = tmp_path / "start.profile"
    profile.write_text("py-sandbox=true\nos-sandbox=none\npython-import=*\n")
    return load_and_parse_config(config_path=profile)._replace(os_sandbox="landlock")


@pytest.fixture(autouse=True)
def _reset_daemon_state():  # type: ignore[no-untyped-def]
    yield
    _os_sandbox._current_daemon = None
    _os_sandbox._startup_counter = 0


def test_linux_runs_every_public_provider() -> None:
    with patch("sys.platform", "linux"):
        assert _os_sandbox.platform_providers() == [
            "none",
            "subprocess",
            "bwrap",
            "firejail",
            "unshare",
            "landlock",
            "qemu",
        ]


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("darwin", ["none", "subprocess"]), ("win32", ["none", "subprocess"])],
)
def test_other_platforms_only_list_their_providers(platform: str, expected: list[str]) -> None:
    with patch("sys.platform", platform):
        assert _os_sandbox.platform_providers() == expected


def test_platform_refusal_does_not_import_the_provider() -> None:
    with (
        patch("sys.platform", "freebsd"),
        patch.object(_os_sandbox, "_load_provider_class", side_effect=AssertionError("imported")),
    ):
        reason = _os_sandbox.provider_unavailable_reason("subprocess")
    assert reason == "os-sandbox 'subprocess' does not run on freebsd, and no provider does yet"


def test_python_sb_imports_without_fcntl(monkeypatch: pytest.MonkeyPatch) -> None:
    # python_sb imports the subprocess client, whose module imported fcntl at the top:
    # on Windows the CLI died on its own import, whatever the provider asked for.
    monkeypatch.setitem(sys.modules, "fcntl", None)  # None makes `import fcntl` fail
    for name in ("pysandboxes.python_sb", "pysandboxes.remote.client_subprocess_sse_daemon"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    importlib.import_module("pysandboxes.python_sb")


def test_supported_platform_asks_the_provider() -> None:
    with (
        patch("sys.platform", "linux"),
        patch.object(_os_sandbox.providers_factory["none"], "unavailable_reason", return_value="probe says no"),
    ):
        assert _os_sandbox.provider_unavailable_reason("none") == "probe says no"


def test_parse_rules_rejects_a_provider_of_another_platform(tmp_path: Path) -> None:
    errors: list[ErrorMsg] = []
    with patch("sys.platform", "darwin"):
        parse_rules(tmp_path / "p.conf", [ConfigLine("os-sandbox=landlock", tmp_path, 1)], errors)
    assert len(errors) == 1
    assert "os-sandbox 'landlock' does not run on darwin. Use one of: subprocess." in errors[0][0]


def test_start_refuses_a_provider_of_another_platform(landlock_rules: AllRules) -> None:
    with patch("sys.platform", "win32"), pytest.raises(ValueError, match="does not run on win32"):
        _os_sandbox.start_daemon(landlock_rules, envs={}, log_level=0, init_fn=None)
    assert _os_sandbox._current_daemon is None


async def test_async_start_refuses_a_provider_of_another_platform(landlock_rules: AllRules) -> None:
    with patch("sys.platform", "win32"), pytest.raises(ValueError, match="does not run on win32"):
        await _os_sandbox.async_start_daemon(landlock_rules, envs={}, log_level=0, init_fn=None)
    assert _os_sandbox._current_daemon is None
