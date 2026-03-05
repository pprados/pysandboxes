"""Unit tests for pysandboxes.remote.tools module."""

import logging
import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

import pytest

from pysandboxes.remote.tools import (
    configure_logging_level,
    from_b85,
    get_default_gateway_info,
    get_venv,
    return_level_parameter,
    suggest_package_installation,
    to_b85,
    which_command,
)


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
            with patch(
                "pysandboxes.remote.tools.shutil.which", return_value=str(expected_path)
            ):
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


class TestConfigureLoggingLevel:
    """Test cases for configure_logging_level function."""

    @patch("logging.getLogger")
    def test_configure_logging_level_error(self, mock_get_logger: Mock) -> None:
        """Test verbose count 0 sets ERROR level."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        result = configure_logging_level(0)

        assert result == logging.ERROR
        mock_logger.setLevel.assert_called_once_with(logging.ERROR)

    @patch("logging.getLogger")
    def test_configure_logging_level_warning(self, mock_get_logger: Mock) -> None:
        """Test verbose count 1 sets WARNING level."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        result = configure_logging_level(1)

        assert result == logging.WARNING
        mock_logger.setLevel.assert_called_once_with(logging.WARNING)

    @patch("logging.getLogger")
    def test_configure_logging_level_info(self, mock_get_logger: Mock) -> None:
        """Test verbose count 2 sets INFO level."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        result = configure_logging_level(2)

        assert result == logging.INFO
        mock_logger.setLevel.assert_called_once_with(logging.INFO)

    @patch("logging.getLogger")
    def test_configure_logging_level_debug(self, mock_get_logger: Mock) -> None:
        """Test verbose count 3 sets DEBUG level."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        result = configure_logging_level(3)

        assert result == logging.DEBUG
        mock_logger.setLevel.assert_called_once_with(logging.DEBUG)

    @patch("logging.getLogger")
    def test_configure_logging_level_notset(self, mock_get_logger: Mock) -> None:
        """Test verbose count 4+ sets NOTSET level."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        result = configure_logging_level(5)

        assert result == logging.NOTSET
        mock_logger.setLevel.assert_called_once_with(logging.NOTSET)


class TestGetDefaultGatewayInfo:
    """Test cases for get_default_gateway_info function."""

    @patch("pysandboxes.remote.tools.netifaces.gateways")
    def test_get_default_gateway_info_ipv4(self, mock_gateways: Mock) -> None:
        """Test getting IPv4 default gateway."""
        mock_gateways.return_value = {
            "default": {2: ("192.168.1.1", "eth0", True)}  # AF_INET = 2
        }

        with patch("netifaces.AF_INET", 2):
            result = get_default_gateway_info()
            assert result == ("192.168.1.1", "eth0", True)

    @patch("pysandboxes.remote.tools.netifaces.gateways")
    def test_get_default_gateway_info_ipv6(self, mock_gateways: Mock) -> None:
        """Test getting IPv6 default gateway when IPv4 not available."""
        mock_gateways.return_value = {
            "default": {10: ("fe80::1", "eth0", True)}  # AF_INET6 = 10
        }

        with patch("netifaces.AF_INET", 2):
            with patch("netifaces.AF_INET6", 10):
                result = get_default_gateway_info()
                assert result == ("fe80::1", "eth0", True)

    @patch("pysandboxes.remote.tools.netifaces.gateways")
    def test_get_default_gateway_info_no_gateway(self, mock_gateways: Mock) -> None:
        """Test no default gateway returns None."""
        mock_gateways.return_value = {"default": {}}

        with patch("netifaces.AF_INET", 2):
            with patch("netifaces.AF_INET6", 10):
                result = get_default_gateway_info()
                assert result is None

    @patch("pysandboxes.remote.tools.netifaces.gateways")
    def test_get_default_gateway_info_key_error(self, mock_gateways: Mock) -> None:
        """Test KeyError handling returns None."""
        mock_gateways.return_value = {}

        result = get_default_gateway_info()
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


class TestReturnLevelParameter:
    """Test cases for return_level_parameter function."""

    def test_return_level_parameter_warn(self) -> None:
        """Test WARNING level returns empty string."""
        result = return_level_parameter(logging.WARN)
        assert result == ""

    def test_return_level_parameter_info(self) -> None:
        """Test INFO level returns '-v'."""
        result = return_level_parameter(logging.INFO)
        assert result == "-v"

    def test_return_level_parameter_debug(self) -> None:
        """Test DEBUG level returns '-vv'."""
        result = return_level_parameter(logging.DEBUG)
        assert result == "-vv"

    def test_return_level_parameter_notset(self) -> None:
        """Test NOTSET level returns '-vvv'."""
        result = return_level_parameter(logging.NOTSET)
        assert result == "-vvv"

    def test_return_level_parameter_unknown(self) -> None:
        """Test unknown level returns '-vvv'."""
        result = return_level_parameter(99999)
        assert result == "-vvv"


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
