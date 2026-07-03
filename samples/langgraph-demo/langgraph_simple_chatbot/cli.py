# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""CLI for the LangGraph chatbot."""

from pathlib import Path

import click
import pysandboxes
from dotenv import load_dotenv

from .agent import create_agent, chat_with_agent
from .console import run_console_chat


load_dotenv()


CONFIG = Path(__file__).parent.parent / ".py-sandboxes"


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """LangGraph chatbot with the fetch and expression tools."""
    pass


@main.command()
@click.option("--model", default="gpt-4o-mini", help="OpenAI model to use", show_default=True)
@click.option("--temperature", default=0.0, type=float, help="Model temperature", show_default=True)
def chat(model: str, temperature: float) -> None:
    """Start an interactive chat session."""
    # Partial mode: only the tool bodies run in the sandbox. `pysandboxes.run()`
    # is the asynchronous entry point -- it arms the profile *and* binds the
    # sandbox loop, which `async with sandboxes(...)` alone does not do.
    pysandboxes.run(
        run_console_chat(model_name=model, temperature=temperature),
        config_path=CONFIG,
    )


@main.command()
@click.argument("message", nargs=-1, required=True)
@click.option("--model", default="gpt-4o-mini", help="OpenAI model to use", show_default=True)
@click.option("--temperature", default=0.0, type=float, help="Model temperature", show_default=True)
def ask(message: tuple[str, ...], model: str, temperature: float) -> None:
    """Ask a single question and get a response."""

    async def run_ask():
        agent = create_agent(model_name=model, temperature=temperature)
        question = " ".join(message)
        response = await chat_with_agent(agent, question)
        click.echo(response)

    pysandboxes.run(run_ask(), config_path=CONFIG)


@main.command()
@click.argument("expression")
def calc(expression: str) -> None:
    """Evaluate a mathematical expression."""

    async def run_calc() -> None:
        from .tools import evaluate_expression

        click.echo(await evaluate_expression.ainvoke({"expression": expression}))

    pysandboxes.run(run_calc(), config_path=CONFIG)


@main.command()
@click.argument("url")
def fetch(url: str) -> None:
    """Fetch a web page and convert it to markdown."""

    async def run_fetch() -> None:
        from .tools import fetch_webpage

        click.echo(await fetch_webpage.ainvoke({"url": url}))

    pysandboxes.run(run_fetch(), config_path=CONFIG)


if __name__ == "__main__":
    main()
