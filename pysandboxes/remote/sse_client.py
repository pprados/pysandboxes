import asyncio
import base64
import json
import pickle
import sys
from traceback import print_exception
from typing import Dict, Optional, Any

import httpx

from pysandboxes.remote.tools import _from_b85, _to_b85

SSE_SERVER_URL: str = "http://127.0.0.1:8000/sse/rpc"



async def sse_client_httpx() -> None:
    """
    Asynchronous Python client to consume Server-Sent Events using httpx.
    """
    print(f"Connecting to SSE server at {SSE_SERVER_URL} using httpx...")

    # Use async context manager for httpx client
    async with httpx.AsyncClient() as client:
        try:
            # Stream the response from the SSE endpoint
            params = {
                "token": "abc123",
                "session_id": "123",
                "function":"builtins:exec",
                "args":_to_b85(["import sys;print('hello');print('error',file=sys.stderr);3+4"]),
                "kwargs":_to_b85({}),
            }
            async with client.stream(
                    "POST", SSE_SERVER_URL,
                    headers={"Accept": "text/event-stream"},
                    json=params,
                    timeout=None) as response:
                response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)

                print("Connection established. Waiting for events...")

                # Buffer for incomplete SSE messages
                buffer: str = ""

                # Iterate over chunks of the response body
                async for chunk in response.aiter_bytes():
                    chunk_str: str = chunk.decode("utf-8")
                    msg=json.loads(chunk_str)
                    if "result" in msg:
                        result=_from_b85(msg["result"])
                        break
                    if "exception" in msg:
                        exception=_from_b85(msg["exception"])
                        raise exception
                    if "stdout" in msg:
                        print(msg["stdout"],end="")
                    if "stderr" in msg:
                        print(msg["stderr"],end="",file=sys.stderr)
                print(f"{result=} {msg=}")

        except httpx.ConnectError as e:
            print(f"Connection error: {e}. Is the server running at {SSE_SERVER_URL}?")
        except httpx.HTTPStatusError as e:
            print(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            print_exception(e)


if __name__ == "__main__":
    # To run this, make sure your FastAPI SSE server is running.
    # Execute this script: python your_client_script_name.py
    asyncio.run(sse_client_httpx())
