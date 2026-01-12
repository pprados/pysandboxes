import asyncio
import importlib
import inspect
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass
from typing import AsyncGenerator, List, Any
from typing import Dict

import uvicorn
from fastapi import FastAPI, Request, Body
from fastapi.responses import StreamingResponse

from . import PATH_RPC, HOST, PORT
from .abstract_start_daemon import BaseStartDaemon
from .catch_stdio import catch_stdio, acatch_stdio
from .tools import _from_b85, _to_b85, is_in_sandbox, \
    set_is_in_sandbox

logger = logging.getLogger(__name__)

from tblib import pickling_support

pickling_support.install()



@dataclass
class RPCPayload(object):
    token: str
    session_id: str
    timeout: float
    function: str
    args: str
    kwargs: str


async def sandbox_daemon(
        token: str,  # TODO: token
        session_id: str,
        function_id: str,
        timeout: float,  # TODO
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
    logger.info(f"(%s) calling %s%s.%s(%s,%s)...",
                session_id,
                "async " if use_async else "",
                module_name, function_name,
                ",".join(map(repr, args)),
                ",".join([f"{k}={repr(v)}" for k, v in kwargs.items()]))

    stdio_queue = asyncio.Queue()

    if use_async:
        async def _set_sandbox_and_catch_stdio():
            set_is_in_sandbox(True)
            return await acatch_stdio(
                stdio_queue,
                function, kwargs, *args)

        task = asyncio.create_task(
            _set_sandbox_and_catch_stdio())
        # task = asyncio.create_task(
        #     acatch_stdio(
        #         stdio_queue,
        #         function, kwargs, *args))
    else:
        def _set_sandbox_and_catch_stdio():
            set_is_in_sandbox(True)
            return catch_stdio(
                stdio_queue,
                function, kwargs, *args)

        task = asyncio.get_running_loop().run_in_executor(None,
                                                          _set_sandbox_and_catch_stdio,
                                                          )
        # task = asyncio.get_running_loop().run_in_executor(None,
        #                                                   catch_stdio,
        #                                                   stdio_queue,
        #                                                   function,
        #                                                   kwargs,
        #                                                   *args,
        #                                                   )
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
        logger.info("(%s) ... return %s", session_id, repr(result["result"]))
        result["result"] = _to_b85(result["result"])
    if "exception" in result:
        logger.info("(%s) ... raise %s", session_id,
                    repr(result["exception"][1]))
        result["exception"] = _to_b85(result["exception"])
    result["session_id"] = session_id
    yield json.dumps(result)


# %%


# TODO: def prepare_main(self, ns=None, /, **kwargs):
# TODO: def prepare_sandbox(self, ns=None, /, **kwargs):
# TODO: def after_sandbox(self, ns=None, /, **kwargs):

def create_daemon() -> uvicorn.Server:
    app = FastAPI()

    @app.get("/")
    async def ping(
    ):
        return {"message": "OK"}

    @app.post(PATH_RPC)
    async def rpc_endpoint(
            request: Request,
            payload: RPCPayload = Body(...,
                                       description="Payload containing code and authentication token.")
    ) -> StreamingResponse:
        """
        SSE endpoint to process a given code string, authenticated by a token,
        and stream back structured results (stdout, stderr, result).
        """
        assert is_in_sandbox()
        # Pass the code and authenticated user_id to the event generator
        return StreamingResponse(
            sandbox_daemon(
                payload.token,
                payload.session_id,
                payload.function,
                payload.timeout,
                _from_b85(payload.args),
                _from_b85(payload.kwargs),
            ),
            media_type="text/event-stream"
        )

    # TODO: https
    return uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT))


class _TaskDaemon(BaseStartDaemon):

    async def _start(self) -> None:
        set_is_in_sandbox(True)
        self.daemon = create_daemon()

        self.task = asyncio.create_task(self.daemon.serve())

    async def close(self) -> None:
        await self.daemon.shutdown()
        logger.info("daemon is shutdown")

    async def join(self) -> int:
        return await self.task


async def main():
    logging.basicConfig(level=logging.INFO)

    task_daemon = _TaskDaemon()
    try:
        await task_daemon.start()
        return await task_daemon.join()
    finally:
        await task_daemon.close()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except SystemExit as e:
        print("capturé par daemon")
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(0)
