# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Staging of the host loader and libraries, the /etc copy, and the interpreter's library directories."""

import logging
import os
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import qemu_sse_daemon as q

_INTERP = Path("/lib64/ld-linux-x86-64.so.2")


class TestStageClosure:
    @pytest.fixture
    def stage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
        merges: list[tuple[Path, str]] = []
        monkeypatch.setattr(q, "_debian_multiarch_triplet", lambda: "tri-linux-gnu")
        monkeypatch.setattr(q, "_merge_full_multiarch_lib_dirs", lambda root, triplet: merges.append((root, triplet)))
        real_is_file = Path.is_file
        monkeypatch.setattr(Path, "is_file", lambda self: False if self == _INTERP else real_is_file(self))

        def run(closure: set[Path], **kwargs: Any) -> list[tuple[str, Path, str]]:
            monkeypatch.setattr(q, "_dynamic_linker_closure_paths", lambda: closure)
            return q._stage_dynamic_linker_closure(tmp_path / "stage", **kwargs)

        run.merges = merges  # type: ignore[attr-defined]
        run.root = (tmp_path / "stage" / "ld_closure_fs").resolve()  # type: ignore[attr-defined]
        return run

    def test_an_empty_closure_stages_nothing(self, stage: Any, tmp_path: Path) -> None:
        assert stage(set()) == []
        assert not (tmp_path / "stage").exists()

    def test_each_file_is_copied_under_the_staged_root_at_its_own_path(self, stage: Any, tmp_path: Path) -> None:
        lib = tmp_path / "libs" / "libfoo.so.1.2"
        lib.parent.mkdir()
        lib.write_text("elf")

        stage({lib})

        staged = stage.root / lib.relative_to("/")
        assert staged.read_text() == "elf"
        assert (staged.parent / "libfoo.so.1").is_symlink()

    def test_the_full_mode_merges_the_multiarch_directories_first(self, stage: Any) -> None:
        stage({Path("/nonexistent/lib.so")}, ld_closure_libs="full")
        stage({Path("/nonexistent/lib.so")})

        assert stage.merges == [(stage.root, "tri-linux-gnu")] * 2

    def test_the_sparse_mode_does_not_merge(self, stage: Any) -> None:
        stage({Path("/nonexistent/lib.so")}, ld_closure_libs="sparse")

        assert stage.merges == []

    @pytest.mark.parametrize(("mode", "copied"), [("full", False), ("sparse", True)])
    def test_a_file_under_the_host_multiarch_tree_is_copied_only_in_sparse_mode(
        self, stage: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, copied: bool
    ) -> None:
        lib = tmp_path / "libs" / "libc.so.6"
        lib.parent.mkdir()
        lib.write_text("elf")
        monkeypatch.setattr(q, "_path_under_host_multiarch_lib", lambda path, triplet: path == lib)

        stage({lib}, ld_closure_libs=mode)

        assert (stage.root / lib.relative_to("/")).exists() is copied

    def test_a_file_that_cannot_be_copied_is_reported_and_skipped(
        self, stage: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        good = tmp_path / "good.so"
        good.write_text("elf")
        bad = tmp_path / "bad.so"

        with caplog.at_level(logging.WARNING, logger=q.logger.name):
            stage({bad, good})

        assert "ld closure: skip" in caplog.text
        assert (stage.root / good.relative_to("/")).exists()

    def test_the_loader_is_staged_under_lib64_when_the_host_has_it(
        self, stage: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = tmp_path / "real-ld.so"
        real.write_text("loader")
        monkeypatch.setattr(Path, "is_file", lambda self: self == _INTERP or os.path.isfile(self))
        monkeypatch.setattr(q.shutil, "copy2", lambda src, dst, **kw: Path(dst).write_text("loader") or str(dst))

        out = stage({tmp_path / "x"})

        assert (stage.root / "lib64" / "ld-linux-x86-64.so.2").read_text() == "loader"
        assert out == [("pysb_lib64", stage.root / "lib64", "/lib64")]

    def test_a_loader_that_cannot_be_copied_is_reported(
        self, stage: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(Path, "is_file", lambda self: self == _INTERP or os.path.isfile(self))

        def copy(src: Any, dst: Any, **kwargs: Any) -> None:
            raise OSError("no loader")

        monkeypatch.setattr(q.shutil, "copy2", copy)

        with caplog.at_level(logging.WARNING, logger=q.logger.name):
            out = stage({tmp_path / "x"})

        assert "could not stage PT_INTERP" in caplog.text
        assert out == [("pysb_lib64", stage.root / "lib64", "/lib64")]

    def test_the_usr_lib_tree_is_mounted_at_both_guest_library_paths(
        self, stage: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def merge(root: Path, triplet: str) -> None:
            (root / "usr" / "lib" / triplet).mkdir(parents=True)

        monkeypatch.setattr(q, "_merge_full_multiarch_lib_dirs", merge)

        out = stage({Path("/nonexistent/lib.so")})

        tree = stage.root / "usr" / "lib" / "tri-linux-gnu"
        assert out == [
            ("pysb_usr_lib_gnu", tree, "/usr/lib/tri-linux-gnu"),
            ("pysb_lib_gnu", tree, "/lib/tri-linux-gnu"),
        ]

    def test_without_a_usr_lib_tree_the_lib_tree_is_mounted_once(
        self, stage: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def merge(root: Path, triplet: str) -> None:
            (root / "lib" / triplet).mkdir(parents=True)

        monkeypatch.setattr(q, "_merge_full_multiarch_lib_dirs", merge)

        out = stage({Path("/nonexistent/lib.so")})

        assert out == [("pysb_lib_gnu", stage.root / "lib" / "tri-linux-gnu", "/lib/tri-linux-gnu")]

    def test_with_no_staged_tree_nothing_is_mounted(self, stage: Any) -> None:
        assert stage({Path("/nonexistent/lib.so")}) == []

    def test_the_mode_is_compared_by_value_not_identity(self, stage: Any) -> None:
        full = "".join(list("full"))  # equal to the literal, but not the same object

        stage({Path("/nonexistent/lib.so")}, ld_closure_libs=full)

        assert stage.merges == [(stage.root, "tri-linux-gnu")]

    def test_a_skipped_multiarch_file_does_not_stop_the_copy_of_the_others(
        self, stage: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = tmp_path / "a_libc.so.6"
        second = tmp_path / "b_libz.so.1"
        for lib in (first, second):
            lib.write_text("elf")
        monkeypatch.setattr(q, "_path_under_host_multiarch_lib", lambda path, triplet: path == first)

        stage({first, second}, ld_closure_libs="".join(list("full")))

        assert not (stage.root / first.relative_to("/")).exists()
        assert (stage.root / second.relative_to("/")).exists()

    def test_a_symlink_of_the_closure_is_copied_as_the_file_it_points_to(self, stage: Any, tmp_path: Path) -> None:
        target = tmp_path / "libreal.so.1.0"
        target.write_text("elf")
        link = tmp_path / "libalias.so"
        link.symlink_to(target)

        stage({link})

        staged = stage.root / link.relative_to("/")
        assert not staged.is_symlink() and staged.read_text() == "elf"

    def test_an_existing_lib64_directory_is_reused(
        self, stage: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (stage.root / "lib64").mkdir(parents=True)
        monkeypatch.setattr(Path, "is_file", lambda self: self == _INTERP or os.path.isfile(self))
        monkeypatch.setattr(q.shutil, "copy2", lambda src, dst, **kw: Path(dst).write_text("loader") or str(dst))

        out = stage({tmp_path / "x"})

        assert out == [("pysb_lib64", stage.root / "lib64", "/lib64")]

    def test_the_loader_is_copied_through_its_links(
        self, stage: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "is_file", lambda self: self == _INTERP or os.path.isfile(self))
        seen: list[tuple[Any, bool]] = []

        def copy(src: Any, dst: Any, follow_symlinks: bool = True) -> str:
            seen.append((Path(src), follow_symlinks))
            Path(dst).write_text("loader")
            return str(dst)

        monkeypatch.setattr(q.shutil, "copy2", copy)

        stage({tmp_path / "x"})

        assert (_INTERP, True) in seen and all(follow for _, follow in seen)

    @pytest.mark.parametrize(
        ("mode", "text"), [("full", "full multiarch merge + ldd seeds"), ("sparse", "sparse ldd + compat seeds")]
    )
    def test_the_staging_is_summarised_in_the_log(
        self, stage: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, mode: str, text: str
    ) -> None:
        (stage.root / "lib" / "tri-linux-gnu").mkdir(parents=True)

        with caplog.at_level(logging.DEBUG, logger=q.logger.name):
            stage({Path("/nonexistent/lib.so")}, ld_closure_libs="".join(list(mode)))

        assert f"(1 ldd objects, {text})" in caplog.text

    def test_nothing_is_logged_when_nothing_is_mounted(self, stage: Any, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger=q.logger.name):
            stage({Path("/nonexistent/lib.so")})

        assert "staged dynamic linker closure" not in caplog.text


class TestEtcCopy:
    def _specs(self, tmp_path: Path) -> tuple[Path, list[tuple[str, Path, str]]]:
        etc = tmp_path / "host-etc"
        etc.mkdir()
        (etc / "hosts").write_text("127.0.0.1 localhost")
        return etc, [("pysb_3", etc, "/etc")]

    def test_the_etc_expose_mount_is_retargeted_at_a_staged_copy(self, tmp_path: Path) -> None:
        etc, specs = self._specs(tmp_path)

        q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        staged = (tmp_path / "stage" / "virtfs_stage_misc").resolve() / "etc"
        assert specs == [("pysb_3", staged, "/etc")]
        assert (staged / "hosts").read_text() == "127.0.0.1 localhost"

    def test_a_trailing_slash_still_designates_etc(self, tmp_path: Path) -> None:
        etc, _ = self._specs(tmp_path)
        specs = [("pysb_0", etc, "/etc/")]

        q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        assert specs[0][1] != etc

    @pytest.mark.parametrize(
        "spec",
        [("pysb_exec_0", "/etc"), ("pysb_run", "/etc"), ("pysb_x", "/etc"), ("pysb_3", "/etc/ssl"), ("other", "/etc")],
    )
    def test_only_a_numbered_file_rule_mount_of_etc_is_copied(self, tmp_path: Path, spec: tuple[str, str]) -> None:
        etc, _ = self._specs(tmp_path)
        specs = [(spec[0], etc, spec[1])]

        q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        assert specs == [(spec[0], etc, spec[1])]
        assert not (tmp_path / "stage" / "virtfs_stage_misc").exists()

    def test_a_missing_host_directory_is_left_alone(self, tmp_path: Path) -> None:
        specs = [("pysb_0", tmp_path / "absent", "/etc")]

        q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        assert specs == [("pysb_0", tmp_path / "absent", "/etc")]

    def test_a_missing_host_directory_does_not_hide_the_next_etc_mount(self, tmp_path: Path) -> None:
        etc, _ = self._specs(tmp_path)
        specs = [("pysb_0", tmp_path / "absent", "/etc"), ("pysb_1", etc, "/etc")]

        q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        assert specs[0][1] == tmp_path / "absent" and specs[1][1] != etc

    def test_an_unrelated_mount_does_not_hide_the_etc_one(self, tmp_path: Path) -> None:
        etc, _ = self._specs(tmp_path)
        specs = [("pysb_run", tmp_path, "/mnt/run"), ("pysb_exec_0", tmp_path, "/etc"), ("pysb_2", etc, "/etc")]

        q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        assert specs[2][1] != etc

    def test_only_the_first_etc_mount_is_copied(self, tmp_path: Path) -> None:
        etc, _ = self._specs(tmp_path)
        specs = [("pysb_0", etc, "/etc"), ("pysb_1", etc, "/etc")]

        q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        assert specs[0][1] != etc and specs[1][1] == etc

    def test_a_failed_copy_is_reported_and_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        etc, specs = self._specs(tmp_path)

        def broken(*args: Any, **kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(q.shutil, "copytree", broken)

        with caplog.at_level(logging.ERROR, logger=q.logger.name), pytest.raises(OSError, match="disk full"):
            q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        assert "copy /etc expose mount failed" in caplog.text
        assert specs == [("pysb_3", etc, "/etc")]

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything")
    def test_a_root_only_file_is_left_out_of_the_copy(self, tmp_path: Path) -> None:
        etc, specs = self._specs(tmp_path)
        secret = etc / "shadow"
        secret.write_text("secret")
        secret.chmod(0)

        q._stage_overlay_etc_expose_mount(tmp_path / "stage", specs)

        assert not (specs[0][1] / "shadow").exists() and (specs[0][1] / "hosts").exists()


class TestInterpreterLibraryDirs:
    @pytest.fixture
    def prefix(self, tmp_path: Path) -> Path:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3.13").write_text("elf")
        (tmp_path / "lib").mkdir()
        return tmp_path

    def test_the_peer_lib_directory_is_added_when_it_holds_libpython(self, prefix: Path) -> None:
        (prefix / "lib" / "libpython3.13.so.1.0").write_text("elf")
        dirs: set[Path] = set()

        q._add_peer_lib_dir_for_executables(dirs, {prefix / "bin" / "python3.13"})

        assert dirs == {(prefix / "lib").resolve()}

    def test_a_peer_lib_directory_without_libpython_is_not_added(self, prefix: Path) -> None:
        (prefix / "lib" / "libother.so").write_text("elf")
        dirs: set[Path] = set()

        q._add_peer_lib_dir_for_executables(dirs, {prefix / "bin" / "python3.13"})

        assert dirs == set()

    def test_a_missing_peer_directory_and_a_non_file_are_skipped(self, tmp_path: Path, prefix: Path) -> None:
        (tmp_path / "other" / "bin").mkdir(parents=True)
        (tmp_path / "other" / "bin" / "python").write_text("elf")
        dirs: set[Path] = set()

        q._add_peer_lib_dir_for_executables(
            dirs, {tmp_path / "other" / "bin" / "python", tmp_path / "bin", tmp_path / "gone"}
        )

        assert dirs == set()

    def test_one_bad_path_does_not_hide_the_next(self, prefix: Path) -> None:
        (prefix / "lib" / "libpython3.13.so").write_text("elf")
        dirs: set[Path] = set()

        q._add_peer_lib_dir_for_executables(dirs, {Path("/nonexistent/python"), prefix / "bin" / "python3.13"})

        assert dirs == {(prefix / "lib").resolve()}

    def test_the_libpython_directory_comes_from_ldd(self, prefix: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        libs = prefix / "elsewhere"
        libs.mkdir()
        python_so = libs / "libpython3.13.so.1.0"
        python_so.write_text("elf")
        libc = prefix / "lib" / "libc.so.6"
        libc.write_text("elf")
        monkeypatch.setattr(q, "_ldd_resolved_paths", lambda path: {python_so, libc})
        dirs: set[Path] = set()

        q._add_libpython_dirs_from_ldd(dirs, {prefix / "bin" / "python3.13"})

        assert dirs == {libs.resolve()}

    def test_ldd_is_not_asked_about_a_path_that_is_not_a_file(
        self, prefix: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[Path] = []

        def ldd(path: Path) -> set[Path]:
            asked.append(path)
            return set()

        monkeypatch.setattr(q, "_ldd_resolved_paths", ldd)

        q._add_libpython_dirs_from_ldd(set(), {prefix / "bin", prefix / "gone"})

        assert asked == []

    def test_a_dependency_that_vanished_is_ignored(self, prefix: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(q, "_ldd_resolved_paths", lambda path: {Path("/nonexistent/libpython3.so")})
        dirs: set[Path] = set()

        q._add_libpython_dirs_from_ldd(dirs, {prefix / "bin" / "python3.13"})

        assert dirs == set()
