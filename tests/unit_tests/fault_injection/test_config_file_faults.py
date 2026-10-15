# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A profile that cannot be read must stop the start: no rule set, in particular no permissive default."""

import os
import sys
from pathlib import Path

import pytest

from pysandboxes.py_sandbox import load_and_parse_config

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")


def test_an_unreadable_profile_raises_instead_of_returning_rules(tmp_path: Path) -> None:
    profile = tmp_path / "unreadable.profile"
    profile.write_text("py-sandbox=true\n")
    profile.chmod(0)
    if os.access(profile, os.R_OK):
        pytest.skip("the process can read it anyway (root)")

    with pytest.raises(PermissionError):
        load_and_parse_config(config_path=profile, envs={})


def test_a_directory_in_place_of_the_profile_raises(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError):
        load_and_parse_config(config_path=tmp_path, envs={})


@pytest.mark.parametrize("content", [b"py-sandbox=true\n\xff\xfe\x00bad\n", b"\x80" * 64])
def test_a_profile_that_is_not_text_raises(tmp_path: Path, content: bytes) -> None:
    profile = tmp_path / "binary.profile"
    profile.write_bytes(content)

    with pytest.raises(UnicodeDecodeError):
        load_and_parse_config(config_path=profile, envs={})
