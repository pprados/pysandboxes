"""Unit tests for pysandboxes.remote.parse_cpython_args module."""

from pathlib import Path
from unittest.mock import Mock, patch

from pysandboxes.config import CONFIG_NAME
from pysandboxes.remote.parse_cpython_args import (
    parse_python_cmd_line,
)


class TestParsePythonCmdLine:
    """Test cases for parse_python_cmd_line function."""

    def test_parse_python_cmd_line_basic_script(self) -> None:
        """Test parsing basic script execution."""
        args = ["-v", "-O", "script.py", "-v", "arg2"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert ["-v", "-O"] == python_parsed
        assert [] == sandboxes_args
        assert ["script.py", "-v", "arg2"] == python_cmd
        assert Path(CONFIG_NAME) == config

    def test_parse_python_cmd_line_with_unknown_args(self) -> None:
        """Test parsing with unknown args (sandbox args)."""
        args = ["-v", "--pysandboxes-config=config", "-O", "script.py"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert ["-v", "-O"] == python_parsed
        assert "--pysandboxes-config=config" not in sandboxes_args
        assert ["script.py"] == python_cmd
        assert Path("config") == config

    def test_parse_python_cmd_line_module_execution(self) -> None:
        """Test parsing module execution with -m."""
        args = ["-B", "-m", "module", "args"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert ["-B"] == python_parsed
        assert sandboxes_args == []
        assert python_cmd == ["-m", "module", "args"]
        assert config == Path(CONFIG_NAME)

    def test_parse_python_cmd_line_command_execution(self) -> None:
        """Test parsing command execution with -c."""
        args = ["-u", "-c", "print('hello world')", "extra"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert ["-u"] == python_parsed
        assert sandboxes_args == []
        assert python_cmd == ["-c", "print('hello world')", "extra"]
        assert config == Path(CONFIG_NAME)

    def test_parse_python_cmd_line_interactive_mode(self) -> None:
        """Test parsing interactive mode (no script/command)."""
        args = ["-i", "-v"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert ["-i", "-v"] == python_parsed

        assert sandboxes_args == []
        assert python_cmd == []
        assert config == Path(CONFIG_NAME)

    def test_parse_python_cmd_line_x_option(self) -> None:
        """Test parsing with -X option."""
        args = ["--env=a=b", "-X", "dev", "-X", "utf8", "script.py", "--param=value"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        # Note: The current implementation may not handle -X correctly
        # This test documents the current behavior
        assert python_parsed == ["-X", "dev", "-X", "utf8"]
        assert sandboxes_args == ["--env=a=b"]
        assert python_cmd == ["script.py", "--param=value"]
        assert config == Path(CONFIG_NAME)

    @patch("sys.exit")
    def test_parse_python_cmd_line_help_flag(self, mock_exit: Mock) -> None:
        """Test parsing with help flag exits."""
        args = ["-h"]

        with patch("builtins.print"):
            parse_python_cmd_line(args)

            mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    def test_parse_python_cmd_line_help_flag_with_question(self, mock_exit: Mock) -> None:
        """Test parsing with -? help flag exits."""
        args = ["-?"]

        with patch("builtins.print"):
            parse_python_cmd_line(args)

            mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    def test_parse_python_cmd_line_help_flag_long(self, mock_exit: Mock) -> None:
        """Test parsing with --help flag exits."""
        args = ["--help"]

        with patch("builtins.print"):
            parse_python_cmd_line(args)

            mock_exit.assert_called_once_with(0)

    def test_parse_python_cmd_line_boolean_flags(self) -> None:
        """Test parsing various boolean flags."""
        args = [
            "-b",
            "-B",
            "-d",
            "-E",
            "-i",
            "-I",
            "-O",
            "-OO",
            "-P",
            "-q",
            "-R",
            "-s",
            "-S",
            "-u",
            "-v",
            "-x",
            "script.py",
        ]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        boolean_flags = [
            "-b",
            "-B",
            "-d",
            "-E",
            "-i",
            "-I",
            "-O",
            "-OO",
            "-P",
            "-q",
            "-R",
            "-s",
            "-S",
            "-u",
            "-v",
            "-x",
        ]
        for flag in boolean_flags:
            assert flag in python_parsed, f"Flag {flag} should be in parsed args"

        assert sandboxes_args == []
        assert python_cmd == ["script.py"]
        assert config == Path(CONFIG_NAME)

    def test_parse_python_cmd_line_mixed_args(self) -> None:
        """Test parsing mixed Python args and sandbox args."""
        args = [
            "-v",
            "--env=a=b",
            "-O",
            "script.py",
            "arg1",
        ]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert "-v" in python_parsed
        assert "-O" in python_parsed
        assert "--env=a=b" in sandboxes_args
        assert python_cmd == ["script.py", "arg1"]
        assert config == Path(CONFIG_NAME)

    def test_parse_python_cmd_line_check_hash_based_pycs(self) -> None:
        """Test parsing --check-hash-based-pycs flag."""
        args = ["--check-hash-based-pycs", "script.py"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert "--check-hash-based-pycs" in python_parsed
        assert python_cmd == ["script.py"]
        assert config == Path(CONFIG_NAME)

    def test_parse_python_cmd_line_empty_args(self) -> None:
        """Test parsing empty arguments list."""
        args: list[str] = []

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert python_parsed == []
        assert sandboxes_args == []
        assert python_cmd == []
        assert config == Path(CONFIG_NAME)

    def test_parse_python_cmd_line_only_sandbox_args(self) -> None:
        """Test parsing with only sandbox arguments."""
        args = ["--env=a=b", "--learn"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        assert python_parsed == []
        assert "--env=a=b" in sandboxes_args
        assert "--learn" in sandboxes_args
        assert python_cmd == []
        assert config == Path(CONFIG_NAME)

    def test_parse_python_cmd_line_preserves_order(self) -> None:
        """Test that argument order is preserved."""
        args = ["-O", "-v", "-B", "script.py", "arg2", "arg1"]

        python_parsed, sandboxes_args, python_cmd, config = parse_python_cmd_line(args)

        # Check that the original order is preserved in python_cmd
        assert python_cmd == ["script.py", "arg2", "arg1"]

        # Python parsed args should contain the flags
        expected_flags = {"-O", "-v", "-B"}
        assert set(python_parsed).issuperset(expected_flags)
        assert config == Path(CONFIG_NAME)
