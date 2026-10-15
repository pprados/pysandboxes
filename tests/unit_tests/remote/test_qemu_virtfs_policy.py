# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""When the QEMU provider stages trees before sharing them, which QEMU binary it picks, and how mounts are ordered."""

import logging
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.remote import qemu_sse_daemon as q
from pysandboxes.sb_types import ConfigLine


class TestStagingMode:
    @pytest.mark.parametrize(
        ("params", "mode"),
        [
            ({}, "auto"),
            ({"virtfs": "ON"}, "on"),
            ({"virtfs": "  Off "}, "off"),
            ({"virtfs": ""}, "auto"),
            ({"virtfs": "   "}, "auto"),
            ({"virtfs": None}, "auto"),
            ({"virtfs_stage": "yes"}, "yes"),
            ({"virtfs_stage": ""}, "auto"),
            ({"virtfs_stage": None}, "auto"),
            ({"virtfs": "off", "virtfs_stage": "on"}, "off"),
            ({"virtfs": 0}, "0"),
        ],
    )
    def test_the_mode_is_normalised_and_the_legacy_alias_is_a_fallback(self, params: dict[str, Any], mode: str) -> None:
        assert q._virtfs_staging_mode(params) == mode


class TestStagingNeeded:
    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
    def test_off_spellings_never_stage(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setattr(q, "_running_in_container", lambda: True)

        assert q._virtfs_stage_exec_needed({"virtfs": value}) is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "On"])
    def test_on_spellings_always_stage(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setattr(q, "_running_in_container", lambda: False)

        assert q._virtfs_stage_exec_needed({"virtfs": value}) is True

    @pytest.mark.parametrize("container", [True, False])
    def test_auto_follows_the_container_detection(self, monkeypatch: pytest.MonkeyPatch, container: bool) -> None:
        monkeypatch.setattr(q, "_running_in_container", lambda: container)

        assert q._virtfs_stage_exec_needed({}) is container
        assert q._virtfs_stage_exec_needed({"virtfs": "auto"}) is container

    @pytest.mark.parametrize("container", [True, False])
    def test_an_unknown_value_warns_and_falls_back_to_auto(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, container: bool
    ) -> None:
        monkeypatch.setattr(q, "_running_in_container", lambda: container)

        with caplog.at_level(logging.WARNING, logger=q.logger.name):
            assert q._virtfs_stage_exec_needed({"virtfs": "maybe"}) is container

        assert "Unknown qemu.virtfs value 'maybe'" in caplog.text


class TestContainerDetection:
    @pytest.fixture(autouse=True)
    def no_markers(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("container", raising=False)
        real_is_file = Path.is_file
        monkeypatch.setattr(
            Path,
            "is_file",
            lambda self: False if str(self) in ("/.dockerenv", "/.containerenv") else real_is_file(self),
        )

    def test_a_bare_host_is_not_a_container(self) -> None:
        assert q._running_in_container() is False

    def test_the_docker_marker_file_is_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "is_file", lambda self: str(self) == "/.dockerenv")

        assert q._running_in_container() is True

    def test_the_podman_marker_file_is_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "is_file", lambda self: str(self) == "/.containerenv")

        assert q._running_in_container() is True

    def test_the_container_variable_is_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("container", "oci")

        assert q._running_in_container() is True

    def test_an_empty_container_variable_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("container", "")

        assert q._running_in_container() is False


class TestQemuBinary:
    def _which(self, monkeypatch: pytest.MonkeyPatch, available: dict[str, str]) -> list[str]:
        asked: list[str] = []

        def which(name: str) -> str | None:
            asked.append(name)
            return available.get(name)

        monkeypatch.setattr(q, "which_command", which)
        return asked

    def test_the_binary_of_the_host_architecture_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(q.platform, "machine", lambda: "aarch64")
        asked = self._which(monkeypatch, {"qemu-system-aarch64": "/opt/qemu-aarch64"})

        assert q._qemu_binary() == "/opt/qemu-aarch64"
        assert asked == ["qemu-system-aarch64"]

    def test_another_architecture_falls_back_to_the_x86_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(q.platform, "machine", lambda: "aarch64")
        asked = self._which(monkeypatch, {"qemu-system-x86_64": "/opt/qemu-x86"})

        assert q._qemu_binary() == "/opt/qemu-x86"
        assert asked == ["qemu-system-aarch64", "qemu-system-x86_64"]

    def test_x86_does_not_ask_twice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        arch = "".join(list("x86_64"))  # equal to the literal, but not the same object
        monkeypatch.setattr(q.platform, "machine", lambda: arch)
        asked = self._which(monkeypatch, {})

        assert q._qemu_binary() == "qemu-system-x86_64"
        assert asked == ["qemu-system-x86_64"]

    @pytest.mark.parametrize("arch", ["xtensa", "zarch", "s390x", "aarch64", "mips"])
    def test_any_other_architecture_falls_back_to_x86(self, monkeypatch: pytest.MonkeyPatch, arch: str) -> None:
        monkeypatch.setattr(q.platform, "machine", lambda: arch)
        self._which(monkeypatch, {"qemu-system-x86_64": "/opt/qemu-x86"})

        assert q._qemu_binary() == "/opt/qemu-x86"

    def test_without_any_binary_the_expected_name_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(q.platform, "machine", lambda: "riscv64")
        self._which(monkeypatch, {})

        assert q._qemu_binary() == "qemu-system-riscv64"


class TestGuestPathKey:
    @pytest.mark.parametrize(("path", "key"), [("/app/", "/app"), ("/app", "/app"), ("/a//b/./c", "/a/b/c")])
    def test_a_trailing_slash_or_dot_segment_does_not_make_a_second_mount(self, path: str, key: str) -> None:
        assert q._norm_guest_path(path) == key


def _expose(path: Path | str, write: bool = False) -> FSExposeRule:
    return FSExposeRule(path=str(path), write=write, config=ConfigLine("expose", Path("profile"), 1))


class TestFileRulesMounts:
    @pytest.fixture(autouse=True)
    def no_exec_dirs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(q, "_execution_dirs_mounts", lambda: [])
        monkeypatch.setattr(q, "_virtfs_stage_exec_needed", lambda params: False)

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            # A real staging copies tens of gigabytes of host libraries; no test here may reach it.
            raise AssertionError("staging must not run")

        for name in (
            "_stage_exec_virtfs_mounts",
            "_merge_staged_virtfs_into_expose_mounts",
            "_rebase_file_expose_hosts_under_staged_app",
            "_stage_overlay_etc_expose_mount",
            "_stage_dynamic_linker_closure",
        ):
            monkeypatch.setattr(q, name, forbidden)

    def _mounts(self, tmp_path: Path, rules: list[Any], **kwargs: Any) -> tuple[list[Any], list[Any]]:
        temp = kwargs.pop("temp", tmp_path / "run")
        temp.mkdir(exist_ok=True)
        return q._file_rules_mounts(EmptyRules._replace(file_rules=tuple(rules)), temp, temp / "pipe", **kwargs)

    def test_each_expose_rule_becomes_a_numbered_mount_at_its_own_path(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()

        specs, mounts = self._mounts(tmp_path, [_expose(tmp_path / "a"), _expose(str(tmp_path / "b") + "/")])

        assert [(t, str(h), g) for t, h, g in specs if t.startswith("pysb_") and t[5:].isdigit()] == [
            ("pysb_0", str((tmp_path / "a").resolve()), str((tmp_path / "a").resolve())),
            ("pysb_1", str((tmp_path / "b").resolve()), str((tmp_path / "b").resolve())),
        ]
        assert [t for t, _ in mounts] == [t for t, _, _ in specs]

    def test_the_number_is_the_position_of_the_rule_not_of_the_mount(self, tmp_path: Path) -> None:
        from pysandboxes.guard_files import IgnoreRule

        (tmp_path / "a").mkdir()
        ignore = IgnoreRule(source="*.env", config=ConfigLine("ignore", Path("profile"), 1))

        specs, _ = self._mounts(tmp_path, [ignore, _expose(tmp_path / "a")])

        assert "pysb_1" in [t for t, _, _ in specs] and "pysb_0" not in [t for t, _, _ in specs]

    def test_a_file_is_shared_through_its_directory(self, tmp_path: Path) -> None:
        file = tmp_path / "data" / "x.txt"
        file.parent.mkdir()
        file.write_text("x")

        specs, _ = self._mounts(tmp_path, [_expose(file)])

        assert specs[0][1] == file.parent.resolve()

    def test_a_missing_path_is_skipped(self, tmp_path: Path) -> None:
        specs, _ = self._mounts(tmp_path, [_expose(tmp_path / "absent")])

        assert [t for t, _, _ in specs] == ["pysb_run"]

    def test_a_missing_path_does_not_hide_the_rules_after_it(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()

        specs, _ = self._mounts(tmp_path, [_expose(tmp_path / "absent"), _expose(tmp_path / "a")])

        assert "pysb_1" in [t for t, _, _ in specs]

    def test_the_run_directory_is_always_shared_at_its_guest_mount(self, tmp_path: Path) -> None:
        specs, mounts = self._mounts(tmp_path, [])

        assert specs == [("pysb_run", tmp_path / "run", q.GUEST_RUN_MOUNT)]
        assert mounts == [("pysb_run", q.GUEST_RUN_MOUNT)]

    def test_a_run_directory_that_does_not_exist_is_not_shared(self, tmp_path: Path) -> None:
        specs, _ = q._file_rules_mounts(EmptyRules, tmp_path / "absent", tmp_path / "pipe")

        assert specs == []

    def test_the_config_directory_is_shared_when_it_exists(self, tmp_path: Path) -> None:
        config = tmp_path / "config"
        config.mkdir()

        specs, mounts = self._mounts(tmp_path, [], config_dir=config)

        assert ("pysb_config", config, q.GUEST_CONFIG_MOUNT) in specs
        assert ("pysb_config", q.GUEST_CONFIG_MOUNT) in mounts

    def test_the_mounts_are_ordered_rules_by_depth_then_config_run_and_the_rest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        shallow = tmp_path / "c"
        shallow.mkdir()
        config = tmp_path / "config"
        config.mkdir()
        monkeypatch.setattr(
            q,
            "_execution_dirs_mounts",
            lambda: [
                ("pysb_exec_0", tmp_path, "/zz/exec"),
                ("other", tmp_path, "/a/other"),
                ("pysb_zzz", tmp_path, "/b/z"),
            ],
        )

        specs, mounts = self._mounts(tmp_path, [_expose(deep), _expose(shallow)], config_dir=config)

        assert [t for t, _ in mounts] == [
            "pysb_1",
            "pysb_0",
            "pysb_config",
            "pysb_run",
            "other",
            "pysb_zzz",
            "pysb_exec_0",
        ]
        assert [t for t, _, _ in specs] == [t for t, _ in mounts]

    @pytest.mark.xfail(
        strict=True,
        reason="`tag[9:]` of 'pysb_exec_1' is '_1', never a digit: the (2, index) order of the exec dirs is dead code",
    )
    def test_the_exec_dirs_follow_their_own_index_whatever_their_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            q,
            "_execution_dirs_mounts",
            lambda: [("pysb_exec_0", tmp_path, "/exec/zero"), ("pysb_exec_1", tmp_path, "/exec/one")],
        )

        _, mounts = self._mounts(tmp_path, [])

        assert [t for t, _ in mounts if t.startswith("pysb_exec")] == ["pysb_exec_0", "pysb_exec_1"]

    def test_an_exec_dir_already_exposed_is_not_mounted_twice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shared = tmp_path / "shared"
        shared.mkdir()
        monkeypatch.setattr(q, "_execution_dirs_mounts", lambda: [("pysb_exec_0", shared, str(shared.resolve()) + "/")])

        specs, _ = self._mounts(tmp_path, [_expose(shared)])

        assert "pysb_exec_0" not in [t for t, _, _ in specs]

    def test_an_already_exposed_exec_dir_does_not_hide_the_next_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shared = tmp_path / "shared"
        shared.mkdir()
        monkeypatch.setattr(
            q,
            "_execution_dirs_mounts",
            lambda: [("pysb_exec_0", shared, str(shared.resolve())), ("pysb_exec_1", tmp_path, "/exec/other")],
        )

        specs, _ = self._mounts(tmp_path, [_expose(shared)])

        assert [t for t, _, _ in specs if t.startswith("pysb_exec")] == ["pysb_exec_1"]

    def test_an_exec_dir_listed_twice_is_mounted_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            q,
            "_execution_dirs_mounts",
            lambda: [("pysb_exec_0", tmp_path, "/exec/x"), ("pysb_exec_1", tmp_path, "/exec/x/")],
        )

        specs, _ = self._mounts(tmp_path, [])

        assert [t for t, _, _ in specs if t.startswith("pysb_exec")] == ["pysb_exec_0"]
