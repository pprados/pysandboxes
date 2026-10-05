"""Unit tests for learning module."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from pysandboxes.learning import (
    _manage_olds_file,
    add_learning_rule,
    generate_config_from_learning,
    is_learning_mode,
    set_learning_mode,
)


class TestGenerateConfigFromLearning:
    """Test cases for generate_config_from_learning function."""

    @patch("pysandboxes.guard_envs.generate_rules")
    @patch("pysandboxes.guard_files.generate_rules")
    @patch("pysandboxes.guard_import.generate_rules")
    @patch("pysandboxes.guard_socket.generate_rules")
    @patch("pysandboxes.learning._manage_olds_file")
    @patch("pysandboxes.learning.is_learning_mode")
    def test_generate_config_with_all_rules(
        self,
        mock_is_learning_mode: Mock,
        mock_manage_olds: Mock,
        mock_socket_rules: Mock,
        mock_import_rules: Mock,
        mock_file_rules: Mock,
        mock_env_rules: Mock,
    ) -> None:
        """Test config generation with all rule types."""
        # Setup mock returns

        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = Path(temp_dir) / "config.conf"
            mock_env_rules.return_value = ["env:HOME", "env:PATH"]
            mock_import_rules.return_value = ["import:os", "import:sys"]
            mock_file_rules.return_value = [
                "file:read:/tmp/*",
                "file:write:/tmp/output",
            ]
            mock_socket_rules.return_value = ["socket:tcp:80", "socket:udp:53"]
            mock_manage_olds.return_value = (test_path, None)
            mock_is_learning_mode.return_value = True

            with (
                patch("pysandboxes.learning._learning_path", Path("test.conf")),
                patch("pysandboxes.learning._save_learning_done", False),
                patch("pysandboxes.eval_rules.generate_rules", return_value=["eval:dynamic"]) as mock_eval_rules,
            ):
                generate_config_from_learning()
                generated = test_path.read_text()

        assert all(
            rule in generated
            for rule in (
                "env:HOME",
                "env:PATH",
                "import:os",
                "import:sys",
                "file:read:/tmp/*",
                "file:write:/tmp/output",
                "socket:tcp:80",
                "socket:udp:53",
                "eval:dynamic",
            )
        )
        mock_env_rules.assert_called_once()
        mock_import_rules.assert_called_once()
        mock_file_rules.assert_called_once()
        mock_socket_rules.assert_called_once()
        mock_eval_rules.assert_called_once()


class TestManageOldsFile:
    """Test cases for _manage_olds_file function."""

    def test_manage_olds_file_new_file(self) -> None:
        """Test managing old files when target doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = Path(temp_dir) / "new_config.conf"

            result_path, old_path = _manage_olds_file(test_path)

            assert result_path == test_path
            assert old_path is None

    def test_manage_olds_file_existing_file(self) -> None:
        """Test managing old files when target already exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = Path(temp_dir) / "existing_config.conf"
            test_path.write_text("existing content")

            result_path, old_path = _manage_olds_file(test_path)

            assert result_path == test_path
            assert old_path is not None
            assert old_path.suffix == ".old"


class TestLearningModeManagement:
    """Test cases for learning mode activation/deactivation."""

    def test_activate_learning(self) -> None:
        """Test activating learning mode."""

        with (
            patch("pysandboxes.learning._learning_path", None),
            patch("pysandboxes.learning._learning_mode", False),
        ):
            set_learning_mode(True)

            # Check that learning mode is activated
            assert is_learning_mode() is True

    def test_stop_learning_mode(self) -> None:
        """Test stopping learning mode."""
        # First activate learning
        with patch("pysandboxes.learning._learning_path", Path("test.conf")):
            set_learning_mode(False)

            # Check that learning mode is stopped
            assert is_learning_mode() is False


class TestAddLearningRule:
    """Test cases for add_learning_rule function."""

    def test_add_learning_rule_when_inactive(self) -> None:
        """Test adding a rule when learning mode is inactive."""
        test_rule = "test_rule"

        with patch("pysandboxes.learning._learning_path", None):
            with patch("pysandboxes.learning._learning") as mock_learning:
                mock_learning_set = Mock()
                mock_learning.add = mock_learning_set.add
                add_learning_rule(test_rule)

                # Rule should not be added when learning is inactive
                mock_learning_set.add.assert_not_called()

    def test_add_learning_rule_duplicate(self) -> None:
        """Adding the same learning rule twice keeps only one copy."""
        test_rule = "duplicate_rule"

        with (
            patch("pysandboxes.learning._learning_path", Path("test.conf")),
            patch("pysandboxes.learning._learning_mode", True),
            patch("pysandboxes.learning._learning", set[str]()) as learned,
        ):
            add_learning_rule(test_rule)
            add_learning_rule(test_rule)

        assert learned == {test_rule}

    def test_add_learning_rule_different_types(self) -> None:
        """Test adding different types of learning rules."""
        rules = [
            "file:/path/to/file",
            "socket:tcp:80",
            "import:code_path",
            "env:VARIABLE_NAME",
        ]

        with (
            patch("pysandboxes.learning._learning_path", Path("test.conf")),
            patch("pysandboxes.learning._learning_mode", True),
            patch("pysandboxes.learning._learning", set[str]()) as learned,
        ):
            for rule in rules:
                add_learning_rule(rule)

        assert learned == set(rules)
