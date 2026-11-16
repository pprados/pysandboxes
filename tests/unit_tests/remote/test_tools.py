"""Unit tests for pysandboxes.remote.tools module."""

import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest  # type: ignore[import-untyped]

from pysandboxes.guard_files import IgnoreRule
from pysandboxes.remote.tools import (
    from_b85,
    get_venv,
    resolve_ignore_paths,
    suggest_package_installation,
    to_b85,
    which_command,
)
from pysandboxes.sb_types import ConfigLine


class TestWhichCommand:
    """Test cases for which_command function."""

    def test_which_command_found_in_known_paths(self) -> None:
        """Test finding command in known system paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_bin = Path(temp_dir) / "bin"
            test_bin.mkdir()
            test_cmd = test_bin / "testcmd"
            test_cmd.write_text("#!/bin/bash\necho test\n")
            test_cmd.chmod(0o755)

            with patch("pysandboxes.remote.tools.known_paths", [test_bin]):
                result = which_command("testcmd")
                assert result == test_cmd

    def test_which_command_found_via_shutil_which(self) -> None:
        """Test finding command via shutil.which fallback."""
        expected_path = Path("/usr/bin/python3")

        with patch("pysandboxes.remote.tools.known_paths", []):
            with patch("pysandboxes.remote.tools.shutil.which", return_value=str(expected_path)):
                result = which_command("python3")
                assert result == expected_path

    def test_which_command_not_found(self) -> None:
        """Test command not found returns None."""
        with patch("pysandboxes.remote.tools.known_paths", []):
            with patch("shutil.which", return_value=None):
                result = which_command("nonexistent_command")
                assert result is None


class TestGetVenv:
    """Test cases for get_venv function."""

    def test_get_venv_in_virtual_environment(self) -> None:
        """Test detecting virtual environment from sys.prefix."""
        with patch("sys.prefix", "/path/to/venv"):
            with patch("sys.base_prefix", "/usr"):
                result = get_venv()
                assert result == "/path/to/venv"

    def test_get_venv_from_environment_variable(self) -> None:
        """Test getting venv from VIRTUAL_ENV environment variable."""
        with patch("sys.prefix", "/usr"):
            with patch("sys.base_prefix", "/usr"):
                with patch.dict(os.environ, {"VIRTUAL_ENV": "/path/to/env"}):
                    result = get_venv()
                    assert result == "/path/to/env"

    def test_get_venv_no_environment(self) -> None:
        """Test no virtual environment detected."""
        with patch("sys.prefix", "/usr"):
            with patch("sys.base_prefix", "/usr"):
                with patch.dict(os.environ, {}, clear=True):
                    result = get_venv()
                    assert result is None


class TestSuggestPackageInstallation:
    """Test cases for suggest_package_installation function."""

    def test_suggest_package_installation_ubuntu(self) -> None:
        """Test Ubuntu package installation suggestion."""
        mock_os_release = 'ID="ubuntu"\nNAME="Ubuntu"\n'

        with patch("sys.platform", "linux"):
            with patch("builtins.open", mock_open(read_data=mock_os_release)):
                result = suggest_package_installation("firejail")

                assert "apt install firejail" in result
                assert "sudo apt update" in result

    def test_suggest_package_installation_centos(self) -> None:
        """Test CentOS package installation suggestion."""
        mock_os_release = 'ID="centos"\nNAME="CentOS"\n'

        with patch("sys.platform", "linux"):
            with patch("builtins.open", mock_open(read_data=mock_os_release)):
                result = suggest_package_installation("firejail")

                assert "yum install firejail" in result

    def test_suggest_package_installation_macos(self) -> None:
        """Test macOS package installation suggestion."""
        with patch("sys.platform", "darwin"):
            result = suggest_package_installation("firejail")

            assert "brew install firejail" in result

    def test_suggest_package_installation_unknown_system(self) -> None:
        """Test unknown system package installation suggestion."""
        with patch("sys.platform", "unknown"):
            result = suggest_package_installation("firejail")

            assert "not explicitly supported" in result
            assert "firejail" in result

    def test_suggest_package_installation_file_not_found(self) -> None:
        """Test handling of missing /etc/os-release file."""
        with patch("sys.platform", "linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                result = suggest_package_installation("firejail")

                # Should fall back to generic Linux suggestion
                assert "package manager" in result.lower()


class TestSerializationFunctions:
    """Test cases for to_b85 and from_b85 functions."""

    def test_to_b85_simple_object(self) -> None:
        """Test serialization of simple object."""
        test_obj = {"key": "value", "number": 42}

        result = to_b85(test_obj)

        assert isinstance(result, str)
        # Verify it's valid base85 by attempting to decode
        deserialized = from_b85(result)
        assert deserialized == test_obj

    def test_from_b85_simple_object(self) -> None:
        """Test deserialization of simple object."""
        test_obj = [1, 2, 3, "test"]
        serialized = to_b85(test_obj)

        result = from_b85(serialized)

        assert result == test_obj

    def test_serialization_roundtrip_complex_object(self) -> None:
        """Test roundtrip serialization of complex object."""
        test_obj = {
            "string": "test",
            "int": 42,
            "float": 3.14159,
            "list": [1, 2, 3],
            "dict": {"nested": True},
            "none": None,
            "bool": False,
        }

        serialized = to_b85(test_obj)
        deserialized = from_b85(serialized)

        assert deserialized == test_obj

    def test_to_b85_none(self) -> None:
        """Test serialization of None."""
        result = to_b85(None)
        assert isinstance(result, str)
        assert from_b85(result) is None

    def test_to_b85_empty_structures(self) -> None:
        """Test serialization of empty structures."""
        test_cases = [{}, [], "", 0]

        for test_obj in test_cases:
            serialized = to_b85(test_obj)
            deserialized = from_b85(serialized)
            assert deserialized == test_obj

    def test_from_b85_invalid_string(self) -> None:
        """Test from_b85 with invalid base85 string."""
        with pytest.raises(pickle.UnpicklingError):
            from_b85("invalid_base85_string!")

    def test_serialization_preserves_types(self) -> None:
        """Test that serialization preserves Python types."""
        test_obj = {
            "tuple": (1, 2, 3),
            "set": {1, 2, 3},
            "bytes": b"binary data",
        }

        serialized = to_b85(test_obj)
        deserialized = from_b85(serialized)

        assert deserialized == test_obj
        assert isinstance(deserialized["tuple"], tuple)
        assert isinstance(deserialized["set"], set)
        assert isinstance(deserialized["bytes"], bytes)


def test_the_transport_survives_arming() -> None:
    """``pickle.loads`` is a guard_api target, and the transport is not user code.

    ``to_b85``/``from_b85`` bind the originals at import, so a profile that
    never mentions pickle keeps a working result and exception path. Resolving
    ``pickle.loads`` as a module attribute at call time would break it.
    """
    from pysandboxes.guard_api import activate_guard, patch_rules
    from pysandboxes.lifecycle import _reset_for_tests, arm

    activate_guard(())
    guarded = patch_rules(learn=False)["pickle.loads"](pickle.loads)
    original = pickle.loads
    pickle.loads = guarded  # type: ignore[assignment]
    try:
        arm()
        assert from_b85(to_b85({"a": 1})) == {"a": 1}
    finally:
        pickle.loads = original  # type: ignore[assignment]
        _reset_for_tests()


def _ignore(pattern: str) -> IgnoreRule:
    return IgnoreRule(pattern, ConfigLine(f"ignore={pattern}", Path(), 1))


class TestResolveIgnorePaths:
    """Shared by bwrap, unshare, firejail, qemu and qemu-microvm: a pattern matched under every

    root a caller passes -- the current directory and every path the profile exposes."""

    def test_no_ignore_rule_resolves_to_nothing(self, tmp_path: Path) -> None:
        assert resolve_ignore_paths([str(tmp_path)], []) == []

    def test_a_pattern_matches_at_the_top_of_a_root(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("TOP=1", encoding="utf-8")

        assert resolve_ignore_paths([str(tmp_path)], [_ignore(".env")]) == [str(tmp_path / ".env")]

    def test_a_pattern_matches_in_a_directory_nested_under_a_root(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".env").write_text("NESTED=1", encoding="utf-8")

        assert resolve_ignore_paths([str(tmp_path)], [_ignore(".env")]) == [str(tmp_path / "sub" / ".env")]

    def test_an_absent_pattern_resolves_to_nothing(self, tmp_path: Path) -> None:
        assert resolve_ignore_paths([str(tmp_path)], [_ignore(".env")]) == []

    def test_a_pattern_naming_a_sub_path_does_not_match_a_basename(self, tmp_path: Path) -> None:
        """``fnmatch`` is applied to the basename alone: a pattern with a path separator matches nothing."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".env").write_text("NESTED=1", encoding="utf-8")

        assert resolve_ignore_paths([str(tmp_path)], [_ignore("sub/.env")]) == []

    def test_a_missing_root_resolves_to_nothing(self, tmp_path: Path) -> None:
        assert resolve_ignore_paths([str(tmp_path / "missing")], [_ignore(".env")]) == []

    def test_a_match_in_a_second_root_outside_the_first_is_found(self, tmp_path: Path) -> None:
        """An exposed path need not sit under the current directory: an unrelated root is walked too."""
        cwd, exposed = tmp_path / "cwd", tmp_path / "exposed"
        cwd.mkdir()
        exposed.mkdir()
        (exposed / ".env").write_text("SECRET=1", encoding="utf-8")

        assert resolve_ignore_paths([str(cwd), str(exposed)], [_ignore(".env")]) == [str(exposed / ".env")]

    def test_a_root_nested_under_another_is_not_walked_twice(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".env").write_text("NESTED=1", encoding="utf-8")

        assert resolve_ignore_paths([str(tmp_path), str(tmp_path / "sub")], [_ignore(".env")]) == [
            str(tmp_path / "sub" / ".env")
        ]

    def test_a_root_that_is_a_file_is_matched_directly_instead_of_walked(self, tmp_path: Path) -> None:
        exposed_file = tmp_path / ".env"
        exposed_file.write_text("SECRET=1", encoding="utf-8")

        assert resolve_ignore_paths([str(exposed_file)], [_ignore(".env")]) == [str(exposed_file)]

    def test_a_symlinked_subdirectory_of_a_root_is_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / ".env").write_text("SECRET=1", encoding="utf-8")
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)

        assert resolve_ignore_paths([str(root)], [_ignore(".env")]) == []
