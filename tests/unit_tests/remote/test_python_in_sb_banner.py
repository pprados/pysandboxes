# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The REPL banner must not crash when the configuration file lies outside the working directory."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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

    assert str(rules.learning_path) in banners[0]
