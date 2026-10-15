# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The host dynamic-linker closure the QEMU guest runs the interpreter against."""

import logging
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import qemu_sse_daemon as q


class TestLibsMode:
    @pytest.mark.parametrize("raw", ["sparse", "SPARSE", " minimal ", "ldd"])
    def test_the_minimal_spellings_mean_sparse(self, raw: str) -> None:
        assert q._normalize_ld_closure_libs_param(raw) == "sparse"

    @pytest.mark.parametrize("raw", ["full", "Wide", "multiarch", "yes", "true", "1", None, "", "  "])
    def test_the_full_spellings_and_the_default_mean_full(self, raw: str | None) -> None:
        assert q._normalize_ld_closure_libs_param(raw) == "full"

    def test_an_unknown_value_warns_and_means_full(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=q.logger.name):
            assert q._normalize_ld_closure_libs_param("tiny") == "full"

        assert "Unknown qemu.ld_closure_libs value 'tiny'" in caplog.text


class TestMultiarchPrefix:
    @pytest.mark.parametrize(
        ("path", "under"),
        [
            ("/lib/x86_64-linux-gnu/libc.so.6", True),
            ("/usr/lib/x86_64-linux-gnu/libm.so.6", True),
            ("/lib/x86_64-linux-gnu", True),
            ("/usr/lib/x86_64-linux-gnu/../x86_64-linux-gnu/libz.so.1", True),
            ("/lib64/ld-linux-x86-64.so.2", False),
            ("/lib/aarch64-linux-gnu/libc.so.6", False),
            ("/opt/lib/x86_64-linux-gnu/libc.so.6", False),
            ("/lib/x86_64-linux-gnux/libc.so.6", False),
            ("/usr/lib/python3/libc.so.6", False),
        ],
    )
    def test_only_a_path_prefix_counts_without_following_links(self, path: str, under: bool) -> None:
        assert q._path_under_host_multiarch_lib(Path(path), "x86_64-linux-gnu") is under


class TestSonameLink:
    def _link(self, directory: Path, name: str) -> Path:
        dest = directory / name
        dest.write_text("elf")
        q._ensure_ld_closure_soname_symlink(dest)
        return dest

    def test_the_soname_points_at_the_versioned_file(self, tmp_path: Path) -> None:
        self._link(tmp_path, "libpcre2-8.so.0.14.0")

        link = tmp_path / "libpcre2-8.so.0"
        assert link.is_symlink() and link.resolve() == (tmp_path / "libpcre2-8.so.0.14.0").resolve()

    @pytest.mark.parametrize("name", ["libfoo.so", "libfoo.so.6", "libfoo.so.x.1", "plain.txt", "libfoo.so.abc"])
    def test_a_file_that_is_already_its_soname_or_has_none_gets_no_link(self, tmp_path: Path, name: str) -> None:
        self._link(tmp_path, name)

        assert [p.name for p in tmp_path.iterdir()] == [name]

    def test_an_existing_file_is_not_replaced(self, tmp_path: Path) -> None:
        (tmp_path / "libfoo.so.1").write_text("real")

        self._link(tmp_path, "libfoo.so.1.2.3")

        assert not (tmp_path / "libfoo.so.1").is_symlink()
        assert (tmp_path / "libfoo.so.1").read_text() == "real"

    def test_an_existing_symlink_is_kept_even_when_dangling(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "libfoo.so.1").symlink_to("gone")

        with caplog.at_level(logging.DEBUG, logger=q.logger.name):
            self._link(tmp_path, "libfoo.so.1.2.3")

        assert "could not soname-symlink" not in caplog.text

        assert (tmp_path / "libfoo.so.1").resolve() == (tmp_path / "gone").resolve()

    def test_a_directory_that_refuses_the_link_does_not_fail_the_staging(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def refuse(self: Path, target: str, **kwargs: object) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(Path, "symlink_to", refuse)

        with caplog.at_level(logging.DEBUG, logger=q.logger.name):
            self._link(tmp_path, "libfoo.so.1.2.3")

        assert "could not soname-symlink" in caplog.text


class TestMultiarchMerge:
    def test_missing_host_directories_are_skipped(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger=q.logger.name):
            q._merge_full_multiarch_lib_dirs(tmp_path, "no-such-triplet-for-test")

        assert list(tmp_path.iterdir()) == []
        assert caplog.text.count("full merge skip missing") == 2


class TestClosure:
    @pytest.fixture
    def libs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
        files = {}
        for name in ("python", "libpython.so", "libm.so", "libc.so", "util", "libutil.so", "compat.so"):
            path = tmp_path / name
            path.write_text("elf")
            files[name] = path
        monkeypatch.setattr(sys, "executable", str(files["python"]))
        monkeypatch.setattr(q, "follow_links_executable", lambda exe, out: None)
        monkeypatch.setattr(q, "_qemu_bootstrap_ldd_seed_executables", lambda: [])
        monkeypatch.setattr(q, "_qemu_guest_overlay_compat_so_seeds", lambda: [])
        return files

    def _ldd(self, monkeypatch: pytest.MonkeyPatch, graph: dict[Path, list[Path]]) -> None:
        monkeypatch.setattr(q, "_ldd_resolved_paths", lambda path: set(graph.get(path, [])))

    def test_the_closure_holds_the_interpreter_and_its_transitive_dependencies(
        self, libs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._ldd(
            monkeypatch,
            {
                libs["python"].resolve(): [libs["libpython.so"], libs["libm.so"]],
                libs["libpython.so"]: [libs["libc.so"]],
                libs["libm.so"]: [libs["libc.so"]],
            },
        )

        closure = q._dynamic_linker_closure_paths()

        assert {libs["python"].resolve(), libs["libpython.so"], libs["libm.so"], libs["libc.so"]} <= closure
        assert libs["util"] not in closure

    def test_a_dependency_cycle_ends(self, libs: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
        self._ldd(
            monkeypatch,
            {
                libs["python"].resolve(): [libs["libm.so"]],
                libs["libm.so"]: [libs["libc.so"]],
                libs["libc.so"]: [libs["libm.so"]],
            },
        )

        assert {libs["libm.so"], libs["libc.so"]} <= q._dynamic_linker_closure_paths()

    def test_a_dependency_that_is_not_a_file_is_left_out_without_hiding_the_others(
        self, libs: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        missing = tmp_path / "libgone.so"
        directory = tmp_path / "libdir.so"
        directory.mkdir()
        graph = {libs["python"].resolve(): [libs["libm.so"], directory, missing]}
        # A list, so the stack pops the missing path first, then the directory, then the library.
        monkeypatch.setattr(q, "_ldd_resolved_paths", lambda path: graph.get(path, []))  # type: ignore[arg-type,return-value]

        closure = q._dynamic_linker_closure_paths()

        assert libs["libm.so"] in closure
        assert missing not in closure and directory not in closure

    def test_the_bootstrap_utilities_and_compat_libraries_are_seeds_too(
        self, libs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(q, "_qemu_bootstrap_ldd_seed_executables", lambda: [libs["util"]])
        monkeypatch.setattr(q, "_qemu_guest_overlay_compat_so_seeds", lambda: [libs["compat.so"]])
        self._ldd(monkeypatch, {libs["util"]: [libs["libutil.so"]]})

        closure = q._dynamic_linker_closure_paths()

        assert {libs["util"], libs["libutil.so"], libs["compat.so"]} <= closure

    def test_the_seeds_added_for_the_nested_overlay_are_logged_only_when_there_are_some(
        self, libs: dict[str, Path], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._ldd(monkeypatch, {})
        with caplog.at_level(logging.DEBUG, logger=q.logger.name):
            q._dynamic_linker_closure_paths()
        assert "bootstrap utility seeds" not in caplog.text and "guest-compat .so seeds" not in caplog.text

        monkeypatch.setattr(q, "_qemu_bootstrap_ldd_seed_executables", lambda: [libs["util"]])
        monkeypatch.setattr(q, "_qemu_guest_overlay_compat_so_seeds", lambda: [libs["compat.so"]])
        with caplog.at_level(logging.DEBUG, logger=q.logger.name):
            q._dynamic_linker_closure_paths()
        assert f"bootstrap utility seeds for nested /lib overlay: ['{libs['util']}']" in caplog.text
        assert "guest-compat .so seeds for nested /lib overlay: ['compat.so']" in caplog.text

    @pytest.mark.skipif(not Path("/lib64/ld-linux-x86-64.so.2").is_file(), reason="no x86-64 loader on this host")
    def test_the_host_loader_is_a_seed(self, libs: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
        self._ldd(monkeypatch, {})

        assert Path("/lib64/ld-linux-x86-64.so.2").resolve() in q._dynamic_linker_closure_paths()

    def test_an_interpreter_that_cannot_be_resolved_gives_an_empty_closure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "executable", str(tmp_path / "no-python"))
        monkeypatch.setattr(q, "follow_links_executable", lambda exe, out: None)

        assert q._dynamic_linker_closure_paths() == set()

    def test_a_launcher_link_leads_to_the_real_interpreter(
        self, libs: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        launcher = tmp_path / "bin" / "python"
        launcher.parent.mkdir()
        launcher.symlink_to(libs["python"])
        monkeypatch.setattr(sys, "executable", str(launcher))
        self._ldd(monkeypatch, {})

        assert libs["python"].resolve() in q._dynamic_linker_closure_paths()
