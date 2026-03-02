import argparse
import logging
import sys
from shutil import which

import anyio
import httpx
import jsonc as json
from dotenv import load_dotenv
from fastmcp import Client

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)


class Configuration:
    """Manages configuration and environment variables for the MCP client."""

    def __init__(self) -> None:
        """Initialize configuration with environment variables."""
        self.load_env()
        self.api_key = self._get_api_key()

    @staticmethod
    def load_env() -> None:
        """Load environment variables from .env file."""
        load_dotenv()

    @staticmethod
    def _get_api_key() -> str:
        """Get the LLM API key from environment."""
        import os

        api_key = os.getenv("GROK_API_KEY")
        if not api_key:
            raise ValueError("GROK_API_KEY not found in environment variables")
        return api_key

    @staticmethod
    def load_config(file_path: str) -> dict:
        """Load server configuration from JSON file."""
        with open(file_path, "r") as f:
            return json.load(f)

    @property
    def llm_api_key(self) -> str:
        """Get the LLM API key."""
        return self.api_key


class LLMClient:
    """Manages communication with the LLM provider."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def get_response(self, messages: list[dict[str, str]]) -> str:
        """Get a response from the LLM."""
        url = "https://api.groq.com/openai/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "messages": messages,
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
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

        except httpx.RequestError as e:
            error_message = f"Error getting LLM response: {str(e)}"
            logging.error(error_message)

            if isinstance(e, httpx.HTTPStatusError):
                status_code = e.response.status_code
                logging.error(f"Status code: {status_code}")
                logging.error(f"Response details: {e.response.text}")

            return f"I encountered an error: {error_message}. Please try again or rephrase your request."


class ChatSession:
    """Orchestrates the interaction between user, LLM, and tools using FastMCP."""

    def __init__(self, client: Client, llm_client: LLMClient) -> None:
        self.client = client
        self.llm_client = llm_client

    async def process_llm_response(self, llm_response: str) -> str:
        """Process the LLM response and execute tools if needed."""
        import json

        try:
            client = self.client
            tool_call = json.loads(llm_response)
            if "tool" in tool_call and "arguments" in tool_call:
                logging.info(f"Executing tool: {tool_call['tool']}")
                logging.info(f"With arguments: {tool_call['arguments']}")

                # for client in self.client:
                if True:
                    tools = await client.list_tools()
                    if any(tool.name == tool_call["tool"] for tool in tools):
                        try:
                            result = await client.call_tool(
                                tool_call["tool"], tool_call["arguments"]
                            )
                            return f"Tool execution result: {result}"
                        except Exception as e:
                            error_msg = f"Error executing tool: {str(e)}"
                            logging.error(error_msg)
                            return error_msg

                return f"No server found with tool: {tool_call['tool']}"
            return llm_response
        except json.JSONDecodeError:
            return llm_response

    async def start(self) -> None:
        """Main chat session handler."""
        # async with anyio.create_task_group() as tg:
        #     for client in self.client:
        #         tg.start_soon(client.__aenter__)

        all_tools = await self.client.list_tools()

        tools_description = "\n".join(
            [
                f"Tool: {tool.name}\nDescription: {tool.description}\nArguments: {tool.inputSchema}"
                for tool in all_tools
            ]
        )

        system_message = (
            "You are a helpful assistant with access to these tools:\n\n"
            f"{tools_description}\n"
            "Choose the appropriate tool based on the user's question. "
            "If no tool is needed, reply directly.\n\n"
            "IMPORTANT: When you need to use a tool, you must ONLY respond with "
            "the exact JSON object format below, nothing else:\n"
            "{\n"
            '    "tool": "tool-name",\n'
            '    "arguments": {\n'
            '        "argument-name": "value"\n'
            "    }\n"
            "}\n\n"
            "After receiving a tool's response:\n"
            "1. Transform the raw data into a natural, conversational response\n"
            "2. Keep responses concise but informative\n"
            "3. Focus on the most relevant information\n"
            "4. Use appropriate context from the user's question\n"
            "5. Avoid simply repeating the raw data\n\n"
            "Please use only the tools that are explicitly defined above."
        )

        messages = [{"role": "system", "content": system_message}]

        while True:
            try:
                user_input = input("You: ").strip().lower()
                if user_input in ["quit", "exit"]:
                    logging.info("\nExiting...")
                    break

                messages.append({"role": "user", "content": user_input})

                llm_response = self.llm_client.get_response(messages)
                logging.info("\nAssistant: %s", llm_response)

                result = await self.process_llm_response(llm_response)
                if result != llm_response:
                    messages.append({"role": "assistant", "content": llm_response})
                    messages.append({"role": "system", "content": result})

                    final_response = self.llm_client.get_response(messages)
                    print(final_response)
                    messages.append(
                        {"role": "assistant", "content": final_response}
                    )
                else:
                    messages.append({"role": "assistant", "content": llm_response})

            except KeyboardInterrupt:
                logging.info("\nExiting...")
                break



async def run(args):
    config = Configuration()
    server_config = config.load_config(args.mcp)

    for mcp_server in server_config["mcpServers"].values():
        if "command" in mcp_server:
            w_command = which(mcp_server["command"])
            if w_command:
                mcp_server["command"] = w_command

    logging.getLogger("mcp").setLevel(logging.DEBUG)
    client = Client(
        server_config,
        roots=["resource://"]
    )
    async with client:

        llm_client = LLMClient(config.llm_api_key)
        chat_session = ChatSession(client, llm_client)
        await chat_session.start()


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
        default="servers_config.json",
        help="The mcp server configuration file.",
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


if __name__ == "__main__":  # TODO: try to place in __init__.py
    # sys.exit(main())  # FIXME
    sys.exit(main_sb())  # Use Full SB by default
