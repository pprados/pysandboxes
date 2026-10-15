# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What the host hands the QEMU guest: the implicit run mount, the masked paths and the NoCloud ISO inputs."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.remote import qemu_setup
from pysandboxes.sb_types import ConfigLine


def _line() -> ConfigLine:
    return ConfigLine("rule", Path("profile"), 1)


class TestImplicitRunMount:
    def test_the_run_directory_is_writable_and_comes_first(self) -> None:
        user_rule = FSExposeRule(path="/data/", write=False, config=_line())

        rules = qemu_setup.augment_all_rules_for_qemu_run_mount(EmptyRules._replace(file_rules=(user_rule,)))

        run_mount, *rest = rules.file_rules
        assert isinstance(run_mount, FSExposeRule)
        assert (run_mount.path, run_mount.write) == (qemu_setup.GUEST_RUN_MOUNT + "/", True)
        assert rest == [user_rule]
        assert run_mount.config.rule == "<implicit qemu run mount>"
        assert run_mount.config.ln == 0

    def test_a_trailing_slash_is_not_doubled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(qemu_setup, "GUEST_RUN_MOUNT", "/mnt/run/")

        (run_mount,) = qemu_setup.augment_all_rules_for_qemu_run_mount(EmptyRules).file_rules

        assert isinstance(run_mount, FSExposeRule)
        assert run_mount.path == "/mnt/run/"

    def test_the_other_rules_are_left_alone(self) -> None:
        rules = qemu_setup.augment_all_rules_for_qemu_run_mount(EmptyRules)

        assert rules._replace(file_rules=()) == EmptyRules


class TestIgnorePaths:
    @pytest.fixture
    def tree(self, tmp_path: Path) -> Path:
        (tmp_path / "keep.txt").write_text("x")
        (tmp_path / ".env").write_text("secret")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".env").write_text("secret")
        (tmp_path / "sub" / "a.log").write_text("x")
        (tmp_path / "logs.d").mkdir()
        return tmp_path

    def _rules(self, *patterns: str) -> list[IgnoreRule]:
        return [IgnoreRule(source=p, config=_line()) for p in patterns]

    def test_no_rule_means_no_path(self, tree: Path) -> None:
        assert qemu_setup._resolve_ignore_paths(str(tree), []) == []

    def test_a_pattern_matches_files_and_directories_at_any_depth(self, tree: Path) -> None:
        found = qemu_setup._resolve_ignore_paths(str(tree), self._rules(".env", "*.log", "logs.d"))

        assert sorted(found) == [".env", "logs.d", "sub/.env", "sub/a.log"]

    def test_the_paths_are_relative_to_the_current_directory(self, tree: Path) -> None:
        assert all(not p.startswith("/") for p in qemu_setup._resolve_ignore_paths(str(tree), self._rules("*")))

    def test_a_missing_directory_gives_nothing(self, tmp_path: Path) -> None:
        assert qemu_setup._resolve_ignore_paths(str(tmp_path / "absent"), self._rules("*")) == []

    def test_a_directory_that_cannot_be_resolved_gives_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken(self: Path, strict: bool = False) -> Path:
            raise OSError("loop")

        monkeypatch.setattr(Path, "resolve", broken)

        assert qemu_setup._resolve_ignore_paths("/anywhere", self._rules("*")) == []

    def test_the_overlay_paths_are_absolute_unique_and_only_from_ignore_rules(self, tree: Path) -> None:
        rules = EmptyRules._replace(
            file_rules=(
                FSExposeRule(path=str(tree), write=True, config=_line()),
                *self._rules(".env"),
                *self._rules(".env"),
            )
        )

        paths = qemu_setup.qemu_ignore_overlay_abs_paths(rules, str(tree))

        base = tree.resolve()
        assert sorted(paths) == [str(base / ".env"), str(base / "sub" / ".env")]

    def test_without_ignore_rules_nothing_is_masked(self, tree: Path) -> None:
        assert qemu_setup.qemu_ignore_overlay_abs_paths(EmptyRules, str(tree)) == []


def _process_config(**values: Any) -> Any:
    return SimpleNamespace(**values)


@pytest.fixture
def iso(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def run(cmd: list[str], **kwargs: Any) -> Any:
        calls.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(qemu_setup.subprocess, "run", run)
    return calls


def _create(temp: Path, config: Any = None, mounts: Any = (), **kwargs: Any) -> Path:
    arguments: dict[str, Any] = dict(
        pipe_basename="  pipe  ", pipe_run_guest_path="/mnt/run", python_version="3.13", python_exe=None
    )
    arguments.update(kwargs)
    return qemu_setup._create_nocloud_iso(temp, config or _process_config(), list(mounts), **arguments)


class TestNoCloudFiles:
    def test_the_inputs_are_written_next_to_the_iso(self, tmp_path: Path, iso: list[dict[str, Any]]) -> None:
        mounts = [("tag0", "/guest/a"), ("tag1", "/guest/b")]

        path = _create(tmp_path, mounts=mounts)

        assert path == tmp_path / qemu_setup.NOCLOUD_ISO
        assert (tmp_path / qemu_setup.PIPE_NAME_FILE).read_text() == "pipe"
        assert (tmp_path / qemu_setup.PYTHON_VERSION_FILE).read_text() == "3.13\n"
        assert (tmp_path / qemu_setup.NINEP_MOUNTS_FILE).read_text() == "tag0 /guest/a\ntag1 /guest/b\n"
        assert (tmp_path / "meta-data").read_text() == "instance-id: pysandboxes-qemu\nlocal-hostname: pysandbox\n"
        assert not (tmp_path / qemu_setup.PYTHON_EXE_FILE).exists()

    def test_no_mount_gives_an_empty_mount_list(self, tmp_path: Path, iso: list[dict[str, Any]]) -> None:
        _create(tmp_path)

        assert (tmp_path / qemu_setup.NINEP_MOUNTS_FILE).read_text() == ""
        assert (tmp_path / qemu_setup.IGNORE_OVERLAYS_FILE).read_text() == ""

    def test_the_host_python_is_recorded_when_given(self, tmp_path: Path, iso: list[dict[str, Any]]) -> None:
        _create(tmp_path, python_exe="/usr/bin/python3.13")

        assert (tmp_path / qemu_setup.PYTHON_EXE_FILE).read_text() == "/usr/bin/python3.13\n"
        assert f"{qemu_setup.PYTHON_EXE_FILE}={qemu_setup.PYTHON_EXE_FILE}" in iso[0]["cmd"]

    def test_the_cloud_config_installs_the_bootstrap_and_runs_it(
        self, tmp_path: Path, iso: list[dict[str, Any]]
    ) -> None:
        _create(tmp_path)

        user_data = (tmp_path / "user-data").read_text()
        assert user_data.startswith("#cloud-config\n")
        assert f"  - path: {qemu_setup.GUEST_BOOTSTRAP_SCRIPT}\n" in user_data
        assert f"  - {qemu_setup.GUEST_BOOTSTRAP_SCRIPT}\n" in user_data
        assert "nameserver 10.0.2.3" in user_data
        assert "debug:" not in user_data and "cloud-init bootcmd (early)" not in user_data

    def test_a_verbose_boot_adds_the_banners_and_debug_block(self, tmp_path: Path, iso: list[dict[str, Any]]) -> None:
        rules = EmptyRules._replace(os_sandbox_params={"show_boot_console": "true"})  # type: ignore[arg-type]

        _create(tmp_path, _process_config(all_rules=rules))

        user_data = (tmp_path / "user-data").read_text()
        assert user_data.startswith("#cloud-config\ndebug:\n  verbosity: 2\n\n")
        assert "cloud-init bootcmd (early)" in user_data
        assert "cloud-init runcmd (before bootstrap)" in user_data

    def test_the_bootstrap_lines_are_indented_into_the_yaml_block(
        self, tmp_path: Path, iso: list[dict[str, Any]]
    ) -> None:
        _create(tmp_path)

        user_data = (tmp_path / "user-data").read_text().splitlines()
        start = user_data.index(f"  - path: {qemu_setup.GUEST_BOOTSTRAP_SCRIPT}")
        assert user_data[start + 1] == "    content: |"
        assert user_data[start + 2].startswith("      ") and user_data[start + 2].strip()


class TestGuestWorkingDirectory:
    def _bootstrap(self, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
        seen: list[Any] = []

        def script(*args: Any, guest_cwd: Any = None, **kwargs: Any) -> str:
            seen.append(guest_cwd)
            return "echo bootstrap"

        monkeypatch.setattr(qemu_setup, "_bootstrap_script_content", script)
        return seen

    def test_the_host_working_directory_of_the_launch_is_used_stripped(
        self, tmp_path: Path, iso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._bootstrap(monkeypatch)

        _create(tmp_path, _process_config(guest_working_dir="  /host/repo  ", all_rules=EmptyRules))

        assert seen == ["/host/repo"]

    @pytest.mark.parametrize("blank", ["", "   ", None, 3])
    def test_a_blank_directory_falls_back_to_the_rules_root(
        self, tmp_path: Path, iso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, blank: Any
    ) -> None:
        seen = self._bootstrap(monkeypatch)
        root = tmp_path / "project"
        root.mkdir()

        _create(tmp_path, _process_config(guest_working_dir=blank, all_rules=EmptyRules._replace(root_path=root)))

        assert seen == [str(root.resolve())]

    def test_without_any_directory_the_bootstrap_decides(
        self, tmp_path: Path, iso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._bootstrap(monkeypatch)

        _create(tmp_path, _process_config(all_rules=SimpleNamespace(root_path="not a path", file_rules=())))

        assert seen == [None]

    def test_the_current_directory_is_used_for_ignored_paths_when_none_is_known(
        self, tmp_path: Path, iso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / ".env").write_text("secret")
        monkeypatch.chdir(project)
        rules = SimpleNamespace(root_path=None, file_rules=(IgnoreRule(source=".env", config=_line()),))

        _create(tmp_path, _process_config(all_rules=rules))

        assert (tmp_path / qemu_setup.IGNORE_OVERLAYS_FILE).read_text() == f"{(project / '.env').resolve()}\n"


class TestIsoCommand:
    def test_the_iso_is_built_from_the_grafted_inputs_in_the_temp_dir(
        self, tmp_path: Path, iso: list[dict[str, Any]]
    ) -> None:
        _create(tmp_path)

        (call,) = iso
        assert call["cmd"] == [
            "genisoimage",
            "-o",
            qemu_setup.NOCLOUD_ISO,
            "-V",
            qemu_setup.CIDATA_LABEL,
            "-J",
            "-r",
            "-graft-points",
            "user-data=user-data",
            "meta-data=meta-data",
            "pipe_name=pipe_name",
            "python_version=python_version",
            "9p_mounts=9p_mounts",
            "ignore_overlays=ignore_overlays",
        ]
        assert call["cwd"] == tmp_path
        assert (call["check"], call["capture_output"], call["timeout"]) == (True, True, 60)

    def test_mkisofs_is_the_fallback_for_a_host_without_genisoimage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tried: list[str] = []

        def run(cmd: list[str], **kwargs: Any) -> Any:
            tried.append(cmd[0])
            if cmd[0] == "genisoimage":
                raise FileNotFoundError
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(qemu_setup.subprocess, "run", run)

        assert _create(tmp_path) == tmp_path / qemu_setup.NOCLOUD_ISO
        assert tried == ["genisoimage", "mkisofs"]

    def test_without_either_tool_the_error_names_them(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def run(cmd: list[str], **kwargs: Any) -> Any:
            raise FileNotFoundError

        monkeypatch.setattr(qemu_setup.subprocess, "run", run)

        with pytest.raises(RuntimeError, match="genisoimage or mkisofs required"):
            _create(tmp_path)

    def test_a_tool_that_fails_is_not_hidden_by_the_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tried: list[str] = []

        def run(cmd: list[str], **kwargs: Any) -> Any:
            tried.append(cmd[0])
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(qemu_setup.subprocess, "run", run)

        with pytest.raises(subprocess.CalledProcessError):
            _create(tmp_path)

        assert tried == ["genisoimage"]


class TestPrepareGuestEnv:
    def test_it_hands_its_arguments_to_the_iso_builder(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        received: list[tuple[Any, ...]] = []

        def create(*args: Any) -> Path:
            received.append(args)
            return tmp_path / "iso"

        monkeypatch.setattr(qemu_setup, "_create_nocloud_iso", create)
        config = _process_config()

        result = qemu_setup.prepare_guest_env(
            tmp_path, config, tmp_path / "run" / "pipe", [("t", "/g")], "/mnt/run", "3.12", "/py", "/cfg/config.pkl"
        )

        assert result == tmp_path / "iso"
        assert received == [(tmp_path, config, [("t", "/g")], "pipe", "/mnt/run", "3.12", "/py", "/cfg/config.pkl")]

    def test_the_defaults_are_the_standard_run_mount_and_python_311(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received: list[tuple[Any, ...]] = []

        def create(*args: Any) -> Path:
            received.append(args)
            return tmp_path

        monkeypatch.setattr(qemu_setup, "_create_nocloud_iso", create)

        qemu_setup.prepare_guest_env(tmp_path, _process_config(), tmp_path / "pipe", [])

        assert received[0][4:] == (qemu_setup.GUEST_RUN_MOUNT, "3.11", None, None)
