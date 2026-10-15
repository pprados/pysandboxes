# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Mount targets, chroot roots, and slirp teardown of the unshare provider."""

import os
from pathlib import Path
from unittest.mock import Mock, patch


from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote.unshare_setup import _ensure_mount_target
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon


class TestEnsureMountTarget:
    def test_a_missing_target_is_created_in_an_existing_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "dir" / "file"
        target.parent.mkdir()

        _ensure_mount_target(str(target), str(tmp_path))

        assert target.is_file()

    def test_a_missing_target_creates_its_parents(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "file"

        _ensure_mount_target(str(target), str(tmp_path))

        assert target.is_file()

    def test_an_absolute_link_is_resolved_inside_the_new_root_even_when_its_directory_exists(
        self, tmp_path: Path
    ) -> None:
        new_root = tmp_path / "root"
        (new_root / "real").mkdir(parents=True)
        link = tmp_path / "link"
        link.symlink_to("/real/file")

        _ensure_mount_target(str(link), str(new_root))

        assert (new_root / "real" / "file").is_file()


class TestUnshareDaemon:
    def test_a_new_daemon_is_stopped_and_keeps_its_python_arguments(self) -> None:
        assert UnshareSSEDaemon("tok", python_args=["-X", "dev"])._python_args == ["-X", "dev"]
        daemon = UnshareSSEDaemon("tok")

        assert daemon._python_args == []
        assert daemon.is_started is False

    def test_the_chroot_roots_are_removed_and_forgotten(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        first, second = daemon._make_chroot_dir(), daemon._make_chroot_dir()

        daemon._remove_chroot_dirs()

        assert not os.path.exists(first)
        assert not os.path.exists(second)
        assert daemon._chroot_dirs == []

    def test_the_flags_come_from_the_template_then_from_the_profile(self) -> None:
        rules = EmptyRules._replace(os_sandbox_params={"with-value": "1", "bare": ""})  # type: ignore[arg-type]

        flags = UnshareSSEDaemon("tok")._get_unshare_flags(rules, dict(os.environ))

        assert flags[-2:] == ["--with-value=1", "--bare"]
        assert len(flags) > 2

    def test_killing_slirp_stops_its_process_and_forgets_it(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        process = Mock()
        daemon._slirp_process_holder[0] = process

        with patch("pysandboxes.remote.unshare_sse_daemon.slirp_remove_temp_files") as remove:
            daemon._kill_slirp()

        process.kill.assert_called_once_with()
        assert daemon._slirp_process_holder[0] is None
        remove.assert_called_once()
        assert daemon._slirp_shutdown_event.is_set()

    def test_killing_slirp_without_a_process_is_harmless(self) -> None:
        daemon = UnshareSSEDaemon("tok")

        with patch("pysandboxes.remote.unshare_sse_daemon.slirp_remove_temp_files"):
            daemon._kill_slirp()

        assert daemon._slirp_process_holder == [None]
