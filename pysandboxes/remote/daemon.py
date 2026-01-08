import asyncio
import importlib
import inspect
import json
import logging
import sys
from dataclasses import dataclass
from typing import AsyncGenerator, List, Any, Tuple
from typing import Dict

import uvicorn
from fastapi import FastAPI, Request, Body
from fastapi.responses import StreamingResponse

from pysandboxes.remote.catch_stdio import catch_stdio, acatch_stdio
from pysandboxes.remote.tools import _from_b85, _to_b85, set_is_in_sandbox

logger = logging.getLogger(__name__)

from tblib import pickling_support

pickling_support.install()

HOST="127.0.0.1"
PORT=8000

@dataclass
class RPCPayload(object):
    token: str
    session_id: str
    function: str
    args: str
    kwargs: str


# TODO: def prepare_main(self, ns=None, /, **kwargs):
def create_daemon() -> uvicorn.Server:
    app = FastAPI()

    # A very basic "database" or configuration store for demonstration
    # In a real app, this would come from a secure source (DB, config file, etc.)
    VALID_AUTH_TOKENS: Dict[str, str] = {
        "mysecrettoken123": "user_alpha",
        "anothersecurekey": "user_beta"
    }

    async def sandbox_daemon(
            token: str,  # TODO: token
            session_id: str,
            function_id: str,
            args: List[Any],
            kwargs: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        module_name, function_name = function_id.split(':', 1)
        module = importlib.import_module(module_name)
        try:
            function = getattr(module, function_name)
        except AttributeError:
            logger.warning("Function %s.%s() not found")
            return
        use_async = inspect.iscoroutinefunction(function)
        logger.error(f"(%s) calling %s%s.%s(%s,%s)...",
                     session_id,
                     "async " if use_async else "",
                     module_name, function_name,
                     ",".join(map(repr, args)),
                     ",".join([f"{k}={repr(v)}" for k, v in kwargs.items()]))

        stdio_queue = asyncio.Queue()

        if use_async:
            task = asyncio.create_task(
                acatch_stdio(
                    stdio_queue,
                    function, kwargs, *args))
        else:
            task = asyncio.get_running_loop().run_in_executor(None,
                                                              catch_stdio,
                                                              stdio_queue,
                                                              function,
                                                              kwargs,
                                                              *args,
                                                              )
        while stdio_queue:
            # msg = stream_queue.get()  # sync mode
            # msg = await loop.run_in_executor(None, stdio_queue.get)  # async mode
            msg = await stdio_queue.get()
            if "result" in msg:
                eval_result = msg["result"]
                break
            elif "exception" in msg:
                break
            elif "stdout" in msg:
                yield json.dumps(msg)
            elif "stderr" in msg:
                yield json.dumps(msg)
        await task
        result = task.result()
        if "result" in result:
            logger.error("(%s) ... return %s", session_id, repr(result["result"]))
            result["result"] = _to_b85(result["result"])
        if "exception" in result:
            logger.error("(%s) ... raise %s", session_id,
                         repr(result["exception"][1]))
            result["exception"] = _to_b85(result["exception"])
        result["session_id"] = session_id
        yield json.dumps(result)

    @app.post("/sse/rpc")
    async def sse_process_endpoint(
            request: Request,
            payload: RPCPayload = Body(...,
                                       description="Payload containing code and authentication token.")
    ) -> StreamingResponse:
        """
        SSE endpoint to process a given code string, authenticated by a token,
        and stream back structured results (stdout, stderr, result).
        """
        # Pass the code and authenticated user_id to the event generator
        return StreamingResponse(
            sandbox_daemon(
                payload.token,
                payload.session_id,
                payload.function,
                _from_b85(payload.args),
                _from_b85(payload.kwargs),
            ),
            media_type="text/event-stream"
        )
    # TODO: https
    return uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT))


def main():
    # TODO: activate sandbox
    sys.stdin.close()

    set_is_in_sandbox(True)

    server=create_daemon()
    server.run()

if __name__ == "__main__":
    # TODO: command line parameters
    main()