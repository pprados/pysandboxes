"""Unit tests for `include "..."` path resolution in a configuration file."""

from pathlib import Path

import pytest

from pysandboxes.py_sandbox import load_and_parse_config


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestConfigInclude:
    """A bare name is looked up next to the profile, a path with a separator from the CWD."""

    def test_relative_to_current_dir_include_is_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`include "./x"` reads x from the current directory, not from the profile's.

        pathlib normalises "./x" to "x", so this used to be treated as a bare name and
        searched next to the profile, where it is not: the include was silently dropped.
        """
        _write(tmp_path / "local.conf", "qemu.show_boot_console=true\n")
        profile = _write(
            tmp_path / "conf" / "test.profile",
            'os-sandbox=qemu\ninclude "./local.conf"  # a comment must not hide it\n',
        )
        monkeypatch.chdir(tmp_path)

        rules = load_and_parse_config(profile)

        assert rules.os_sandbox_params.get("show_boot_console") == "true"

    def test_bare_name_include_is_read_next_to_the_profile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path / "conf" / "local.conf", "qemu.show_boot_console=true\n")
        profile = _write(
            tmp_path / "conf" / "test.profile",
            'os-sandbox=qemu\ninclude "local.conf"\n',
        )
        monkeypatch.chdir(tmp_path)

        rules = load_and_parse_config(profile)

        assert rules.os_sandbox_params.get("show_boot_console") == "true"

    def test_missing_include_is_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An absent optional override leaves the rest of the profile usable."""
        profile = _write(
            tmp_path / "conf" / "test.profile",
            'os-sandbox=qemu\ninclude "./absent.conf"\nqemu.memory=1G\n',
        )
        monkeypatch.chdir(tmp_path)

        rules = load_and_parse_config(profile)

        assert rules.os_sandbox_params.get("memory") == "1G"
        assert "show_boot_console" not in rules.os_sandbox_params
