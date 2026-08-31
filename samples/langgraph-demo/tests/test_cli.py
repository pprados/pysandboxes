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

    def test_calc_refuses_a_call_before_resolving_any_name(self) -> None:
        """The eval guard rejects the call, ahead of the interpreter.

        The profile declares ``eval-syntax=arith, compare``, which admits no
        call at all. `sqrt(16)` is therefore refused while the expression is
        parsed and rewritten, before Python ever has to know whether `sqrt`
        names anything. The refusal, not a NameError, is the point: it is what
        the sandbox contributes over a plain eval().
        """
        result = self.runner.invoke(calc, ["sqrt(16)"])
        assert result.exit_code == 0
        assert "not allowed" in result.output
        assert "refused by the sandbox" in result.output

    def test_calc_reports_a_name_the_tool_does_not_define(self) -> None:
        """The applicative layer is still a plain eval() with no namespace.

        No math namespace is injected: an applicative feature layer around
        eval() is exactly what makes a reader unsure who blocked what. A bare
        name is simply undefined, and the tool reports it. Written without a
        call on purpose, so this stays a NameError whatever the eval profile
        allows.
        """
        result = self.runner.invoke(calc, ["foo + 1"])
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
