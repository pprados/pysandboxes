import argparse
import asyncio
import importlib
import inspect
import json
import logging
import sys
from dataclasses import dataclass
from typing import AsyncGenerator, List, Any, Optional
from typing import Dict

import uvicorn
from fastapi import FastAPI, Request, Body
from fastapi.responses import StreamingResponse

from .parameters import HOST, PORT, PATH_RPC
from .abstract_start_daemon import BaseStartDaemon
from .tools import _from_b85, _to_b85, is_in_sandbox, \
    set_is_in_sandbox, configure_logging_level

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
    from .catch_stdio import catch_stdio, acatch_stdio

    module_name, function_name = function_id.split(':', 1)
    module = importlib.import_module(module_name)
    try:
        function = getattr(module, function_name)
    except AttributeError:
        logger.warning("Function %s.%s() not found", module, function_name)
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

def create_uvicorn_daemon(log_level: int) -> uvicorn.Server:
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
    return uvicorn.Server(uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level=log_level))


class _LocalTaskDaemon(BaseStartDaemon):

    async def _start(self, envs: Dict[str, str],
                     log_level: int) -> None:  # FIXME: use envs ?
        set_is_in_sandbox(True)
        self.daemon = create_uvicorn_daemon(log_level)

        self.task = asyncio.create_task(self.daemon.serve())

    async def close(self) -> None:
        await self.daemon.shutdown()
        logger.info("daemon is shutdown")

    async def join(self) -> int:
        return await self.task


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stard a Python-sandbox daemon inside --outer-sandbox argument."
    )

    # Add the verbose argument.
    # action='count' is key here: it counts how many times the argument is present.
    parser.add_argument(
        '-v', '--verbose',
        action='count',
        default=0,  # Default value if no -v is provided
        help='Increase output verbosity. Use -v for INFO, -vv for DEBUG, -vvv for all messages.'
    )

    # Add the --outer-sandbox argument
    # type=str: Specifies that the argument's value should be treated as a string.
    # help: Provides a description for the argument in the help message.
    # default=None: Sets a default value if the argument is not provided.
    parser.add_argument(
        "--outer-sandbox",
        type=str,
        help="Specifies the \"outer\" sandbox provider (e.g., 'firejail', 'docker').",
        default=None
    )

    # Parse the arguments provided by the user
    args = parser.parse_args()

    # Access the value of --sandbox-provider
    outer_sandbox: Optional[str] = args.outer_sandbox
    assert outer_sandbox, "--outer-sandbox is required"
    log_level = configure_logging_level(args.verbose)

    logging.info(
        f"Start a py-sandbox encapsulated in an os-sandox of type '{outer_sandbox}'")
    # FIXME activate_sandboxes(dict(os.environ), args_rules=None, outer_sandbox=outer_sandbox)
    task_daemon = _LocalTaskDaemon()
    try:
        await task_daemon.start(log_level)
        return await task_daemon.join()
    finally:
        await task_daemon.close()


if __name__ == "__main__":
    rc = 0
    try:
        rc = asyncio.run(main())
    except SystemExit as e:
        rc = int(e.code)
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        rc = -1
    sys.exit(rc)
