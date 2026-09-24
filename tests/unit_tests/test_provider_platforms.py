# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Each provider declares the platforms it runs on, and nothing starts it elsewhere.

The tag lives in the registry so it can be read without importing the provider:
on Windows, the subprocess provider's module does not even import (no ``fcntl``).
"""

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
def subprocess_rules(tmp_path: Path) -> AllRules:
    profile = tmp_path / "start.profile"
    profile.write_text("py-sandbox=true\nos-sandbox=subprocess\npython-import=*\n")
    with patch("sys.platform", "linux"):
        return load_and_parse_config(config_path=profile)


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
    [("darwin", ["none", "subprocess"]), ("win32", ["none"])],
)
def test_other_platforms_only_list_their_providers(platform: str, expected: list[str]) -> None:
    with patch("sys.platform", platform):
        assert _os_sandbox.platform_providers() == expected


def test_platform_refusal_does_not_import_the_provider() -> None:
    with (
        patch("sys.platform", "win32"),
        patch.object(_os_sandbox, "_load_provider_class", side_effect=AssertionError("imported")),
    ):
        reason = _os_sandbox.provider_unavailable_reason("subprocess")
    assert reason == "os-sandbox 'subprocess' does not run on win32, and no provider does yet"


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


def test_start_refuses_a_provider_of_another_platform(subprocess_rules: AllRules) -> None:
    with patch("sys.platform", "win32"), pytest.raises(ValueError, match="does not run on win32"):
        _os_sandbox.start_daemon(subprocess_rules, envs={}, log_level=0, init_fn=None)
    assert _os_sandbox._current_daemon is None


async def test_async_start_refuses_a_provider_of_another_platform(subprocess_rules: AllRules) -> None:
    with patch("sys.platform", "win32"), pytest.raises(ValueError, match="does not run on win32"):
        await _os_sandbox.async_start_daemon(subprocess_rules, envs={}, log_level=0, init_fn=None)
    assert _os_sandbox._current_daemon is None
