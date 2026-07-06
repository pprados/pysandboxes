# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""LangGraph agent implementation."""

import os
from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from .tools import evaluate_expression, fetch_webpage


class AgentState(TypedDict):
    """State definition for the agent graph."""

    messages: Annotated[Sequence[BaseMessage], add_messages]


def create_agent(model_name: str = "gpt-4o-mini", temperature: float = 0) -> CompiledStateGraph:
    """
    Create a LangGraph agent with the fetch and expression tools.

    Args:
        model_name: The OpenAI model to use
        temperature: Temperature for the model

    Returns:
        A compiled LangGraph agent
    """
    tools = [fetch_webpage, evaluate_expression]

    kwargs = {"model": model_name, "temperature": temperature}
    if base_url := os.environ.get("OPENAI_BASE_URL"):
        kwargs["base_url"] = base_url
    if api_key := os.environ.get("OPENAI_API_KEY"):
        kwargs["api_key"] = api_key
    llm = ChatOpenAI(**kwargs)
    llm_with_tools = llm.bind_tools(tools)

    def should_continue(state: AgentState) -> str:
        """Determine if we should continue or end the conversation."""
        messages = state["messages"]
        last_message = messages[-1]

        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return END

    def call_model(state: AgentState) -> dict:
        """Call the language model."""
        messages = state["messages"]

        if not any(isinstance(msg, SystemMessage) for msg in messages):
            system_message = SystemMessage(
                content=(
                    "You are a helpful AI assistant with access to tools. "
                    "You can:\n"
                    "1. Evaluate mathematical expressions using the "
                    "evaluate_expression tool\n"
                    "2. Fetch and convert web pages to markdown using the "
                    "fetch_webpage tool\n\n"
                    "You must use them for any live page content or any "
                    "computation; do not answer from memory alone."
                )
            )
            messages = [system_message] + list(messages)

        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    workflow = StateGraph(AgentState)

    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(tools))

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
    )

    workflow.add_edge("tools", "agent")

    return workflow.compile()


async def chat_with_agent(agent: CompiledStateGraph, message: str) -> str:
    """
    Send a message to the agent and get the response.

    Args:
        agent: The compiled LangGraph agent
        message: The user message

    Returns:
        The agent's response as a string
    """
    result = await agent.ainvoke({"messages": [HumanMessage(content=message)]})

    return result["messages"][-1].content
