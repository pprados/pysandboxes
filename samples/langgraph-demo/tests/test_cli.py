# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests for the CLI module."""

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from langgraph_simple_chatbot.cli import calc, main


class TestCLI:
    """Tests for CLI commands."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_main_help(self) -> None:
        """Test main help command."""
        result = self.runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "LangGraph chatbot" in result.output

    def test_calc_command(self) -> None:
        """Test calc command."""
        result = self.runner.invoke(calc, ["2+2"])
        assert result.exit_code == 0
        assert "4" in result.output

    def test_calc_refuses_a_name_the_tool_does_not_define(self) -> None:
        """The tool is a plain eval() with an emptied __builtins__.

        No math namespace is injected any more: an applicative feature layer
        around eval() is exactly what makes a reader unsure who blocked what.
        `sqrt` is therefore simply undefined, and the tool reports it.
        """
        result = self.runner.invoke(calc, ["sqrt(16)"])
        assert result.exit_code == 0
        assert "NameError" in result.output

    def test_ask_command(self) -> None:
        """Test ask command."""
        with patch("langgraph_simple_chatbot.cli.chat_with_agent") as mock_chat:
            mock_chat.return_value = AsyncMock(return_value="Response")

            with patch("langgraph_simple_chatbot.cli.create_agent") as mock_create:
                mock_create.return_value = AsyncMock()

                result = self.runner.invoke(main, ["ask", "What", "is", "2+2?"])

                assert result.exit_code == 0

    def test_fetch_command(self) -> None:
        """Test fetch command.

        The tool is patched where it is defined, not on the CLI module: the
        command imports it inside its own body, so there is no module-level
        attribute to replace.
        """
        with patch("langgraph_simple_chatbot.tools.fetch_webpage") as mock_fetcher:
            mock_fetcher.ainvoke = AsyncMock(return_value="# Test Page")

            result = self.runner.invoke(main, ["fetch", "https://example.com"])

            assert result.exit_code == 0
