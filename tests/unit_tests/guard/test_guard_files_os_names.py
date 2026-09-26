# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""An ignored file must stay ignored under every name the file system gives it.

``ignore=`` is the one deny rule of guard_files: a spelling the rule does not match,
but the file system resolves to the ignored file, reads it. Windows and macOS each
accept spellings Linux does not: a case variant, an NTFS stream, a trailing dot, a
short 8.3 name, a device prefix. Each test is skipped where its spelling does not
reach the ignored file, so it runs exactly where the bypass would be real.
"""

import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.guard_files import _apply_dest_to_src_rules, _without_ntfs_streams
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import activate_guard_files_rules

_SECRET = "SECRET=1"
_windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows file names")


def _arm(directory: Path, ignore: str) -> None:
    activate_guard_files_rules(
        [ConfigLine(f"expose-rw={directory}", Path(), 0), ConfigLine(f"ignore={ignore}", Path(), 1)]
    )


def _is_ignored(path: str) -> bool:
    return _apply_dest_to_src_rules(path, write=False)[0] is None


def _reaches_the_secret(path: str) -> bool:
    try:
        return Path(path).read_text() == _SECRET
    except OSError:
        return False


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    """An ignored `.env`. The rules are armed by each test, once it checked its premise unguarded."""
    env = tmp_path / ".env"
    env.write_text(_SECRET)
    return env


def test_a_case_variant_of_an_ignored_name_is_ignored(env_file: Path) -> None:
    """APFS and NTFS ignore case by default, and fnmatch follows the case of the OS, not of the disk."""
    variant = str(env_file.with_name(".ENV"))
    if not _reaches_the_secret(variant):
        pytest.skip("case-sensitive file system: .ENV is another file")
    _arm(env_file.parent, ".env")

    assert _is_ignored(variant)


def test_macos_matches_an_ignored_name_whatever_its_case(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    _arm(env_file.parent, ".env")

    assert _is_ignored(str(env_file.with_name(".ENV")))


def test_a_link_to_an_ignored_file_is_ignored(env_file: Path) -> None:
    link = env_file.with_name("innocent")
    try:
        link.symlink_to(env_file)
    except OSError:
        pytest.skip("symbolic links need a privilege this account lacks")
    _arm(env_file.parent, ".env")

    assert _is_ignored(str(link))


@_windows
def test_the_data_stream_of_an_ignored_file_is_ignored(env_file: Path) -> None:
    stream = f"{env_file}::$DATA"
    assert _reaches_the_secret(stream)
    _arm(env_file.parent, ".env")

    assert _is_ignored(stream)


@_windows
def test_a_directory_stream_does_not_escape_an_ignored_directory(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secretdir"
    secret_dir.mkdir()
    (secret_dir / "file").write_text(_SECRET)
    name = f"{secret_dir}::$INDEX_ALLOCATION\\file"
    assert _reaches_the_secret(name)
    _arm(tmp_path, f"{secret_dir}\\*")

    assert _is_ignored(name)


@pytest.mark.parametrize(
    ("path", "plain"),
    [
        ("C:\\d\\.env::$DATA", "C:\\d\\.env"),
        (".env:stream", ".env"),
        ("C:\\secretdir::$INDEX_ALLOCATION\\file", "C:\\secretdir\\file"),
        ("C:\\d\\.env", "C:\\d\\.env"),
    ],
)
def test_the_ntfs_streams_are_stripped_from_every_component(path: str, plain: str) -> None:
    assert _without_ntfs_streams(path) == plain


@_windows
@pytest.mark.parametrize("suffix", [".", " ", ". ."])
def test_a_trailing_dot_or_space_does_not_hide_an_ignored_name(env_file: Path, suffix: str) -> None:
    name = f"{env_file}{suffix}"
    assert _reaches_the_secret(name)
    _arm(env_file.parent, ".env")

    assert _is_ignored(name)


def _short_name(path: Path) -> str:
    # A string, not a list: list2cmdline would escape the quotes cmd needs.
    result = subprocess.run(f'cmd /c for %I in ("{path}") do @echo %~sI', capture_output=True, text=True, check=True)
    return result.stdout.strip()


@_windows
def test_the_short_name_of_an_ignored_file_is_ignored(tmp_path: Path) -> None:
    # A name longer than 8.3 gets a short alias only where 8.3 generation is enabled.
    secret = tmp_path / "credentials.secret"
    secret.write_text(_SECRET)
    short = _short_name(secret)
    if Path(short).name.lower() == secret.name:
        pytest.skip("8.3 name generation is disabled on this volume")
    assert _reaches_the_secret(short)
    _arm(tmp_path, "credentials.secret")

    assert _is_ignored(short)


@_windows
@pytest.mark.parametrize("prefix", ["\\\\?\\", "\\\\.\\"])
def test_a_device_prefix_does_not_escape_an_absolute_ignore_rule(tmp_path: Path, prefix: str) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text(_SECRET)
    name = f"{prefix}{secret}"
    assert _reaches_the_secret(name)
    _arm(tmp_path, str(secret))

    assert _is_ignored(name)


@_windows
def test_an_administrative_share_does_not_escape_an_absolute_ignore_rule(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text(_SECRET)
    drive, rest = os.path.splitdrive(str(secret))
    name = f"\\\\localhost\\{drive[0]}${rest}"
    if not _reaches_the_secret(name):
        pytest.skip("the administrative share is not reachable here")
    _arm(tmp_path, str(secret))

    assert _is_ignored(name)


@pytest.fixture
def linked_tmp_dir() -> Iterator[Path]:
    if not os.path.islink("/tmp"):
        pytest.skip("/tmp is not a symbolic link here")
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        yield Path(directory)


def test_an_exposed_directory_under_a_linked_tmp_is_writable_by_both_names(linked_tmp_dir: Path) -> None:
    """macOS links /tmp to /private/tmp: a rule written with either name covers both."""
    activate_guard_files_rules([ConfigLine(f"expose-rw={linked_tmp_dir}", Path(), 0)])

    assert _apply_dest_to_src_rules(f"{linked_tmp_dir}/file", write=True)[0] is not None
    assert _apply_dest_to_src_rules(f"{os.path.realpath(linked_tmp_dir)}/file", write=True)[0] is not None
