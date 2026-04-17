# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import argparse
import logging
import os
import sys
from pathlib import Path
from shutil import which
from typing import Any, Dict, List

import anyio
import httpx
import jsonc as json
from dotenv import load_dotenv
from fastmcp import Client
from pysandboxes.tools import resolve_env_variables

from .provider_registry import ResolvedChatModel, resolve_chat_model

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


class Configuration:
    """Manages configuration and environment variables for the MCP client."""

    def __init__(self) -> None:
        """Initialize configuration with environment variables."""
        self.load_env()
        self.api_key = self._get_api_key()
        self.chat: ResolvedChatModel = resolve_chat_model()

    @staticmethod
    def load_env() -> None:
        """Load environment variables from .env file."""
        load_dotenv()

    @staticmethod
    def _get_api_key() -> str:
        """Get the LLM API key from environment."""
        import os

        api_key = os.getenv("API_KEY")
        if not api_key:
            raise ValueError("API_KEY not found in environment variables")
        return api_key

    @staticmethod
    def load_config(file_path: str) -> Dict[str, Any]:
        """Load server configuration from JSONC file."""
        body = Path(file_path).read_text()
        body = resolve_env_variables(body, os.environ)
        return json.loads(body)

    @property
    def llm_api_key(self) -> str:
        """Get the LLM API key."""
        return self.api_key

    @property
    def chat_completions_url(self) -> str:
        """OpenAI-compatible chat completions URL for the selected provider."""
        return self.chat.chat_completions_url

    @property
    def llm_model(self) -> str:
        """Remote model name passed to the provider API."""
        return self.chat.model


def _extract_first_json(text: str) -> Dict[str, Any] | List[Any] | None:
    decoder: json.JSONDecoder = json.JSONDecoder()

    for i in range(len(text)):
        # A valid JSON object MUST start with '{' (for dict) or '[' (for list)
        if text[i] in ("{",):
            try:
                # We use scan_once to find the first valid object
                obj: Dict[str, Any] | List[Any]
                end_index: int
                sub_text: str = text[i:].strip()
                obj, end_index = decoder.raw_decode(sub_text)
                return obj

            except json.JSONDecodeError:
                continue

    return None


class LLMClient:
    """Manages communication with the LLM provider."""

    def __init__(self, api_key: str, chat_completions_url: str, model: str) -> None:
        self.api_key = api_key
        self.chat_completions_url = chat_completions_url
        self.model = model

    def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Get a response from the LLM."""
        url = self.chat_completions_url

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "messages": messages,
            "model": self.model,
            "temperature": 0.7,
            "max_tokens": 4096,
            "top_p": 1,
            "stream": False,
            "stop": None,
        }

        try:
            with httpx.Client() as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
                # return '{"tool": "fetch_webpage","arguments": {"url": "http://www.google.com"}}'

        except httpx.RequestError as e:
            error_message = f"Error getting LLM response: {str(e)}"
            logger.error(error_message)

            if isinstance(e, httpx.HTTPStatusError):
                status_code = e.response.status_code
                logger.error(f"Status code: {status_code}")
                logger.error(f"Response details: {e.response.text}")

            return f"I encountered an error: {error_message}. Please try again or rephrase your request."


class ChatSession:
    """Orchestrates the interaction between user, LLM, and tools using FastMCP."""

    def __init__(self, client: Client, llm_client: LLMClient) -> None:
        self.client = client
        self.llm_client = llm_client

    async def process_llm_response(self, llm_response: str) -> str:
        """Process the LLM response and execute tools or resources if needed."""
        import json

        try:
            client = self.client
            action = _extract_first_json(llm_response)
            if (
                action
                and isinstance(action, dict)
                and "tool" in action
                and "arguments" in action
            ):
                logger.info(f"Executing tool: {action['tool']}")
                logger.info(f"With arguments: {action['arguments']}")

                tools = await client.list_tools()
                if any(tool.name == action["tool"] for tool in tools):
                    try:
                        result = await client.call_tool(
                            action["tool"], action["arguments"]
                        )
                        return f"Tool execution result: {'  '.join([x.text for x in result.content])}"
                    except Exception as e:
                        error_msg = f"Error executing tool: {str(e)}"
                        logger.error(error_msg)
                        return error_msg

                return f"No server found with tool: {action['tool']}"

            elif action and isinstance(action, dict) and "resource" in action:
                logger.info(f"Reading resource: {action['resource']}")

                try:
                    results = await client.read_resource(action["resource"])
                    result = "\n".join((result.text for result in results))
                    return f"Resource content: {result}"
                except Exception as e:
                    error_msg = f"Error reading resource: {str(e)}"
                    logger.error(error_msg)
                    return error_msg

            return llm_response
        except json.JSONDecodeError:
            return llm_response

    async def start(self) -> None:
        """Main chat session handler."""
        messages = await self.initialize()

        while True:
            try:
                user_input = input("You: ").strip().lower()
                if user_input in ["quit", "exit"]:
                    logger.info("\nExiting...")
                    break

                final_response = await self.invoke_llm(messages, user_input)
                print(final_response)

            except KeyboardInterrupt:
                logger.info("\nExiting...")
                break

    async def invoke_llm(self, messages: List[Dict[str, str]], user_input: str) -> str:
        messages.append({"role": "user", "content": user_input})
        llm_response = self.llm_client.get_response(messages)
        logger.info("\nAssistant: %s", llm_response)
        result = await self.process_llm_response(llm_response)
        if result != llm_response:
            messages.append({"role": "assistant", "content": llm_response})
            messages.append({"role": "system", "content": result})

            final_response = self.llm_client.get_response(messages)
            messages.append({"role": "assistant", "content": final_response})
            return final_response
        else:
            messages.append({"role": "assistant", "content": llm_response})
            return llm_response

    async def initialize(self) -> List[Dict[str, str]]:
        all_tools = await self.client.list_tools()
        all_resources = await self.client.list_resources()
        all_resource_templates = await self.client.list_resource_templates()
        tools_description = "\n".join(
            [
                f"Tool: {tool.name}\n"
                f"Description: {tool.description}\n"
                f"Arguments: {tool.inputSchema}"
                for tool in all_tools
            ]
        )
        resources_list = "\n".join(
            [
                f"Resource URI: {res.uri}\n"
                f"Name: {res.name}\n"
                f"Description: {res.description}\n"
                f"MIME Type: {res.mimeType}"
                for res in all_resources
            ]
        )
        resource_templates_list = "\n".join(
            [
                f"Resource Template: {res.uriTemplate}\n"
                f"Name: {res.name}\n"
                f"Description: {res.description}\n"
                f"MIME Type: {res.mimeType}"
                for res in all_resource_templates
            ]
        )
        system_message = (
            "You are a helpful assistant with access to tools " "and resources.\n\n"
        )
        if tools_description:
            system_message += f"Available tools:\n{tools_description}\n\n"
        if resources_list:
            system_message += f"Available resources:\n{resources_list}\n\n"
        if resource_templates_list:
            system_message += (
                f"Available resource templates:\n{resource_templates_list}\n\n"
            )
        system_message += (
            "Choose the appropriate tool or resource based on the "
            "user's question. "
            "If no tool or resource is needed, reply directly.\n\n"
            "IMPORTANT: When you need to use a tool, respond ONLY with:\n"
            "{\n"
            '    "tool": "tool-name",\n'
            '    "arguments": {\n'
            '        "argument-name": "value"\n'
            "    }\n"
            "}\n"
            "and nothing else.\n\n"
            "IMPORTANT: When you need to access a resource, respond ONLY with:\n"
            "{\n"
            '    "resource": "resource-uri"\n'
            "}\n"
            "and nothing else.\n\n"
            "After receiving a response:\n"
            "1. Transform the raw data into a natural, "
            "conversational response\n"
            "2. Keep responses concise but informative\n"
            "3. Focus on the most relevant information\n"
            "4. Use appropriate context from the user's question\n"
            "5. Avoid simply repeating the raw data\n\n"
            "Use only the tools and resources explicitly defined above."
        )
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_message}]
        return messages


async def run(args: argparse.Namespace) -> None:
    config = Configuration()
    server_config = config.load_config(args.mcp)

    for mcp_server in server_config["mcpServers"].values():
        if "command" in mcp_server:
            w_command = which(Path(mcp_server["command"]))
            if w_command:
                mcp_server["command"] = w_command
            elif mcp_server["command"] in ("python", "python3"):
                mcp_server["command"] = sys.executable
            else:
                logger.debug(
                    "Impossible to find the command %s", repr(mcp_server["command"])
                )

    logging.getLogger("mcp").setLevel(logging.WARNING)
    client = Client(server_config, roots=[str(Path("./resources").resolve().as_uri())])
    async with client:

        llm_client = LLMClient(
            config.llm_api_key,
            config.chat_completions_url,
            config.llm_model,
        )
        chat_session = ChatSession(client, llm_client)
        if args.print:
            logger.info("Invoke ")
            final_response = await chat_session.invoke_llm(
                await chat_session.initialize(), args.print
            )
            print(final_response)
        else:
            await chat_session.start()
    await client.close()
    logger.debug("End of run")


def main() -> int:
    """Initialize and run the chat session."""
    parser = argparse.ArgumentParser(
        prog="mcp_client",
        description="Run a MCP-client with FastMCP",
    )
    parser.add_argument(
        "-c",
        dest="mcp",
        type=str,
        required=False,
        default="servers_config.jsonc",
        help="The mcp server configuration file.",
    )

    parser.add_argument(
        "-p",
        dest="print",
        type=str,
        required=False,
        default=None,
        help="Print response and exit (useful for pipes).",
    )

    anyio.run(run, parser.parse_args())
    return 0


def main_sb() -> int:
    import sys

    # Manage recursivity if main_sb is called from __main__
    if __name__ not in sys.modules:
        return main()

    sys.argv = [__file__, "-m", globals()["__spec__"].name] + sys.argv[1:]
    from pysandboxes.python_sb import main as python_sb

    # Manage recursivity
    del sys.modules[__name__]

    return python_sb()  # Launch 'python-sb'


if __name__ == "__main__":
    rc = main()  # main() mcp client without sandbox
    # rc=main_sb()  # Use Full SB
    if rc:
        sys.exit(rc)
