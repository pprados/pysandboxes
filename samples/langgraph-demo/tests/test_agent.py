# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests for the agent module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from langgraph_simple_chatbot.agent import chat_with_agent, create_agent


class TestAgent:
    """Tests for the agent functionality."""

    def test_create_agent(self) -> None:
        """Test agent creation."""
        with patch("langgraph_simple_chatbot.agent.ChatOpenAI"):
            agent = create_agent()
            assert agent is not None

    @pytest.mark.asyncio
    async def test_chat_with_agent(self) -> None:
        """Test chat interaction with agent."""
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            return_value={"messages": [HumanMessage(content="Hello"), AIMessage(content="Hi there!")]}
        )

        response = await chat_with_agent(mock_agent, "Hello")

        assert response == "Hi there!"
        mock_agent.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_with_calculator_call(self) -> None:
        """Test agent making a calculator tool call."""
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            return_value={"messages": [HumanMessage(content="What is 2+2?"), AIMessage(content="The result is 4")]}
        )

        response = await chat_with_agent(mock_agent, "What is 2+2?")

        assert "4" in response
