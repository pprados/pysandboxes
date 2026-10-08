# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The unshare provider's pure helpers: ignore masks, flags, chroot reachability, setup config."""

import os
from pathlib import Path

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import IgnoreRule
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote.unshare_setup import UnshareSetupConfig, _ensure_mount_target, _is_reachable_in_chroot
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon, _resolve_ignore_paths
from pysandboxes.sb_types import ConfigLine


def _ignore(pattern: str) -> IgnoreRule:
    return IgnoreRule(source=pattern, config=ConfigLine(f"ignore={pattern}", Path(), 0))


def test_no_ignore_rule_masks_nothing(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1")

    assert _resolve_ignore_paths(str(tmp_path), []) == []


def test_ignored_files_and_directories_are_found_at_any_depth(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "app" / "conf").mkdir(parents=True)
    (tmp_path / "app" / "conf" / ".env").write_text("SECRET=2")
    (tmp_path / "app" / "keys.pem").write_text("key")
    (tmp_path / "app" / "main.py").write_text("")
    (tmp_path / "secrets").mkdir()

    masked = _resolve_ignore_paths(str(tmp_path), [_ignore(".env"), _ignore("*.pem"), _ignore("secrets")])

    assert sorted(masked) == [".env", "app/conf/.env", "app/keys.pem", "secrets"]


def test_a_missing_directory_masks_nothing(tmp_path: Path) -> None:
    assert _resolve_ignore_paths(str(tmp_path / "missing"), [_ignore(".env")]) == []


def test_profile_parameters_become_unshare_flags() -> None:
    rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"propagation": "private", "kill-child": ""}))
    envs: dict[str, str] = {}

    flags = UnshareSSEDaemon._get_unshare_flags(None, rules, envs)  # type: ignore[arg-type]

    assert flags[-2:] == ["--propagation=private", "--kill-child"]
    assert envs == {"UID": str(os.getuid()), "GID": str(os.getgid())}
    assert not any("${" in flag for flag in flags)


def test_the_setup_config_survives_its_json_round_trip() -> None:
    config = UnshareSetupConfig(
        dns_servers=["10.0.2.3"],
        hosts=["10.0.2.2 host"],
        mounts_ro=[("/usr", "/usr")],
        mounts_rw=[("/tmp/w", "/work")],
        named_pipe="/tmp/pipe",
        netfilter_rules=["-A OUTPUT -j DROP"],
        current_dir="/work",
        ignore_paths=[".env"],
        sandbox_envs={"HOME": "/work"},
        chroot_dir="/tmp/root",
    )

    assert UnshareSetupConfig.from_json(config.to_json()) == config


def test_an_older_setup_config_defaults_the_optional_fields() -> None:
    config = UnshareSetupConfig.from_json(
        '{"dns_servers": [], "hosts": [], "mounts_ro": [], "mounts_rw": [], "named_pipe": "p", '
        '"netfilter_rules": [], "current_dir": "/", "chroot_dir": "/r"}'
    )

    assert config.ignore_paths == []
    assert config.sandbox_envs == {}


def test_a_plain_file_in_the_chroot_is_reachable(tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "hosts").write_text("")

    assert _is_reachable_in_chroot(str(tmp_path / "etc" / "hosts"), str(tmp_path))
    assert not _is_reachable_in_chroot(str(tmp_path / "etc" / "missing"), str(tmp_path))


def test_an_absolute_link_resolves_against_the_chroot_not_the_host(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True)
    (root / "run").mkdir()
    (root / "run" / "resolv.conf").write_text("")
    (root / "etc" / "resolv.conf").symlink_to("/run/resolv.conf")
    # /etc/hostname exists on the host, never inside this chroot.
    (root / "etc" / "hostname").symlink_to("/etc/hostname")

    assert _is_reachable_in_chroot(str(root / "etc" / "resolv.conf"), str(root))
    assert not _is_reachable_in_chroot(str(root / "etc" / "hostname"), str(root))


def test_a_relative_link_escaping_the_chroot_is_not_reachable(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True)
    (tmp_path / "outside").write_text("host file")
    (root / "etc" / "leak").symlink_to("../../outside")

    assert not _is_reachable_in_chroot(str(root / "etc" / "leak"), str(root))


def test_a_link_loop_is_not_reachable(tmp_path: Path) -> None:
    (tmp_path / "a").symlink_to("b")
    (tmp_path / "b").symlink_to("a")

    assert not _is_reachable_in_chroot(str(tmp_path / "a"), str(tmp_path), max_hops=5)


def test_a_mount_target_is_created_inside_the_chroot_through_an_absolute_link(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True)
    link = root / "etc" / "resolv.conf"
    link.symlink_to("/run/systemd/resolv.conf")

    _ensure_mount_target(str(link), str(root))

    assert (root / "run" / "systemd" / "resolv.conf").is_file()


def test_a_missing_mount_target_is_created(tmp_path: Path) -> None:
    target = tmp_path / "root" / "etc" / "hosts"

    _ensure_mount_target(str(target), str(tmp_path / "root"))

    assert target.is_file()
