"""Unit tests for `include "..."` path resolution in a configuration file."""

import sys
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

    @pytest.mark.skipif(
        sys.platform == "win32", reason="the profile names a Linux provider, which does not run on Windows"
    )
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

    @pytest.mark.skipif(
        sys.platform == "win32", reason="the profile names a Linux provider, which does not run on Windows"
    )
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

    @pytest.mark.skipif(
        sys.platform == "win32", reason="the profile names a Linux provider, which does not run on Windows"
    )
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

    @pytest.mark.parametrize("platform", ["linux", "win32"])
    def test_platform_include_is_ignored_on_other_platforms(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
    ) -> None:
        _write(tmp_path / "conf" / "macos.profile", "python-import=macos_dependency\n")
        profile = _write(
            tmp_path / "conf" / "test.profile",
            'os-sandbox=subprocess\ninclude-platform=darwin "macos.profile"\n',
        )
        monkeypatch.setattr("pysandboxes.py_sandbox.sys.platform", platform)

        rules = load_and_parse_config(profile)

        assert not any(line.rule == "python-import=macos_dependency" for line in rules.config)

    def test_platform_include_is_loaded_only_on_matching_platform(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path / "conf" / "macos.profile", "python-import=macos_dependency\n")
        profile = _write(
            tmp_path / "conf" / "test.profile",
            'os-sandbox=subprocess\ninclude-platform=darwin "macos.profile"\n',
        )
        monkeypatch.setattr("pysandboxes.py_sandbox.sys.platform", "darwin")

        rules = load_and_parse_config(profile)

        assert any(line.rule == "python-import=macos_dependency" for line in rules.config)


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


def test_a_module_run_with_dash_m_finds_its_package_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m pkg.mod` names the module `__main__`: its spec still carries the package."""
    import importlib.util

    site = tmp_path / "site"
    _write(site / "mainpkg" / "__init__.py", "")
    _write(site / "mainpkg" / "mod.py", "")
    packaged = _write(site / "mainpkg" / CONFIG_NAME, "learn=false\n")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.find_spec("mainpkg.mod")
    caller_globals: dict[str, object] = {"__name__": "__main__", "__spec__": spec, "search": _search_module_config}

    exec("result = search(None)", caller_globals)

    assert caller_globals["result"] == packaged


def test_a_plain_script_still_uses_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    caller_globals: dict[str, object] = {"__name__": "__main__", "__spec__": None, "search": _search_module_config}

    exec("result = search(None)", caller_globals)

    assert caller_globals["result"] == tmp_path / CONFIG_NAME


def test_nearest_package_config_wins_over_the_top_package_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile in the sub-package hides the one of its parent package."""
    site = tmp_path / "site"
    _write(site / "deeppkg" / "__init__.py", "")
    _write(site / "deeppkg" / CONFIG_NAME, "learn=true\n")
    _write(site / "deeppkg" / "sub" / "__init__.py", "")
    nearest = _write(site / "deeppkg" / "sub" / CONFIG_NAME, "learn=false\n")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.chdir(tmp_path)
    caller_globals: dict[str, object] = {"__name__": "deeppkg.sub.mod", "search": _search_module_config}

    exec("result = search(None)", caller_globals)

    assert caller_globals["result"] == nearest


def test_load_and_parse_config_reads_the_profile_packaged_with_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare profile name is searched in the caller's package before the working directory."""
    site = tmp_path / "site"
    _write(site / "loadpkg" / "__init__.py", "")
    _write(site / "loadpkg" / CONFIG_NAME, "os-sandbox=subprocess\nqemu.memory=1G\n")
    cwd = tmp_path / "elsewhere"
    _write(cwd / CONFIG_NAME, "os-sandbox=subprocess\nqemu.memory=2G\n")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.chdir(cwd)
    caller_globals: dict[str, object] = {"__name__": "loadpkg.mod", "load": load_and_parse_config}

    exec("result = load(None)", caller_globals)

    assert "memory" not in caller_globals["result"].os_sandbox_params  # type: ignore[attr-defined]
    assert any(line.rule == "qemu.memory=1G" for line in caller_globals["result"].config)  # type: ignore[attr-defined]


def test_platform_include_of_another_platform_sorting_below_the_current_one_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the exact platform name matches: "win32" sorts after "linux" and must still be skipped."""
    _write(tmp_path / "conf" / "windows.profile", "python-import=windows_dependency\n")
    profile = _write(
        tmp_path / "conf" / "test.profile",
        'os-sandbox=subprocess\ninclude-platform=win32 "windows.profile"\n',
    )
    monkeypatch.setattr("pysandboxes.py_sandbox.sys.platform", "linux")

    rules = load_and_parse_config(profile)

    assert not any(line.rule == "python-import=windows_dependency" for line in rules.config)


def test_a_skipped_platform_include_does_not_drop_the_lines_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "conf" / "macos.profile", "python-import=macos_dependency\n")
    _write(tmp_path / "conf" / "other.profile", "python-import=other_dependency\n")
    profile = _write(
        tmp_path / "conf" / "test.profile",
        'os-sandbox=subprocess\ninclude-platform=darwin "macos.profile"\ninclude "other.profile"\n'
        "python-import=after_dependency\n",
    )
    monkeypatch.setattr("pysandboxes.py_sandbox.sys.platform", "linux")

    rules = load_and_parse_config(profile)

    rule_texts = {line.rule for line in rules.config}
    assert {"python-import=other_dependency", "python-import=after_dependency"} <= rule_texts


@pytest.mark.skipif(sys.platform == "win32", reason="the profile names a Linux provider, which does not run on Windows")
def test_provider_parameters_are_kept_for_any_provider_name(tmp_path: Path) -> None:
    """`bwrap.*` lines are parsed by the bwrap provider, whatever the provider name sorts like."""
    profile = _write(tmp_path / "test.profile", "os-sandbox=bwrap\nbwrap.share-net=yes\n")

    rules = load_and_parse_config(profile)

    assert dict(rules.os_sandbox_params) == {"share-net": "yes"}


@pytest.mark.parametrize(
    ("extra", "provider"),
    [("learn=out.profile\n", "subprocess"), ("", "bwrap")],
)
@pytest.mark.skipif(sys.platform == "win32", reason="the profile names a Linux provider, which does not run on Windows")
def test_only_a_learning_run_is_forced_to_the_subprocess_provider(tmp_path: Path, extra: str, provider: str) -> None:
    profile = _write(tmp_path / "test.profile", f"os-sandbox=bwrap\n{extra}")

    assert load_and_parse_config(profile).os_sandbox == provider


def test_a_package_named_in_capitals_has_its_packaged_config_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = tmp_path / "site"
    _write(site / "CapsPkg" / "__init__.py", "")
    packaged = _write(site / "CapsPkg" / CONFIG_NAME, "learn=false\n")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.chdir(tmp_path)
    caller_globals: dict[str, object] = {"__name__": "CapsPkg.mod", "search": _search_module_config}

    exec("result = search(None)", caller_globals)

    assert caller_globals["result"] == packaged
