"""Unit tests for `include "..."` path resolution in a configuration file."""

from pathlib import Path

import pytest

from pysandboxes.config import CONFIG_NAME
from pysandboxes.py_sandbox import _search_module_config, load_and_parse_config


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


def test_plain_module_caller_without_resources_falls_back_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain top-level caller module, rejected by `files()`, ends the search instead of looping."""
    calls: list[str] = []

    def files_rejecting_plain_modules(anchor: str) -> Path:
        calls.append(anchor)
        if len(calls) > 10:
            raise RuntimeError(f"unbounded lookup: {calls[:3]}...")
        raise TypeError(f"{anchor!r} is not a package")

    monkeypatch.setattr("importlib.resources.files", files_rejecting_plain_modules)
    monkeypatch.chdir(tmp_path)
    caller_globals: dict[str, object] = {"__name__": "plainmod", "search": _search_module_config}

    exec("result = search(None)", caller_globals)

    assert caller_globals["result"] == tmp_path / CONFIG_NAME
    assert calls == ["plainmod"]


def test_packaged_config_is_found_outside_the_package_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller package's own profile is used wherever the CWD is, and a same-named CWD decoy is not."""
    site = tmp_path / "site"
    packaged = _write(site / "auditpkg" / CONFIG_NAME, "learn=false\n")
    _write(site / "auditpkg" / "__init__.py", "")
    cwd = tmp_path / "elsewhere"
    _write(cwd / "auditpkg" / CONFIG_NAME, "learn=true\n")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.chdir(cwd)
    caller_globals: dict[str, object] = {"__name__": "auditpkg.mod", "search": _search_module_config}

    exec("result = search(None)", caller_globals)

    assert caller_globals["result"] == packaged


def test_a_sub_package_config_is_found_when_the_top_package_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nearest package holding a profile wins: the top package of a sub-package caller may hold none."""
    site = tmp_path / "site"
    _write(site / "nestpkg" / "__init__.py", "")
    _write(site / "nestpkg" / "sub" / "__init__.py", "")
    packaged = _write(site / "nestpkg" / "sub" / CONFIG_NAME, "learn=false\n")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.chdir(tmp_path)
    caller_globals: dict[str, object] = {"__name__": "nestpkg.sub.mod", "search": _search_module_config}

    exec("result = search(None)", caller_globals)

    assert caller_globals["result"] == packaged
