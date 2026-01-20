#!/usr/bin/env python3
import argparse
import asyncio
import importlib
import inspect
import json
import logging
import os
import sys
import traceback
from asyncio import CancelledError
from dataclasses import dataclass
from logging import getLogger
from typing import AsyncGenerator, Any, Optional
from typing import Dict

from tblib import pickling_support
from uvicorn import Server

from .parameters import PATH_RPC, HOST, PORT
from .sse_sandbox import SSESandbox
from ..tools import set_is_in_sandbox,is_in_sandbox
from .tools import to_b85, configure_logging_level, END_OF_FILE, \
    from_b85, set_pdeathsig
from ..manage_loop import sandbox_loop, get_sandbox_loop, set_sandbox_loop
from ..py_sandbox import AllRules
from ..types import ConfigLines, Args, Envs

logger = logging.getLogger(__name__)

pickling_support.install()


@dataclass
class RPCPayload(object):
    session_id: str
    timeout: float
    function: str
    args: str
    kwargs: str


def _sse_msg(data: str):
    return "data:" + data + "\n\n"


def create_uvicorn_daemon(token: str) -> 'uvicorn.Server':
    import uvicorn

    from fastapi import FastAPI, Request, Body, HTTPException
    from fastapi.responses import StreamingResponse

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
        set_is_in_sandbox(True)
        logger.debug(request.headers["Authorization"])
        if ("Authorization" not in request.headers or
                request.headers["Authorization"] != f"Bearer {token}"):
            logger.error(
                "Invalid token")
            raise HTTPException(status_code=401, detail="Invalid token")
        logger.debug(f"{asyncio.get_running_loop()=} {id(asyncio.get_running_loop())}")
        assert is_in_sandbox()
        # Pass the code and authenticated user_id to the event generator
        return StreamingResponse(
            sandbox_daemon(
                payload.session_id,
                payload.function,
                payload.timeout,
                from_b85(payload.args),
                from_b85(payload.kwargs),
            ),
            media_type="text/event-stream"
        )

    # TODO: https

    # Extract current logging configuration
    # If not logger exist, try to duplicate the root logger parameters
    root_logger = logging.getLogger("uvicorn.error")
    if root_logger.handlers:
        root_handler = root_logger.handlers[0]
    else:
        root_handler = logging.StreamHandler(stream=sys.stderr)  # FIXME: a tester
        # root_handler=logging.StreamHandler(stream="ext://sys.stdout")  # FIXME: a tester. Pb de capture de flus
    fmt = getattr(root_handler.formatter, "_fmt",
                  '%(levelname)s:%(name)s:%(message)s')
    if root_stream := getattr(root_handler, "stream", None):
        if stream_name := getattr(root_stream, "name", None):
            if stream_name == "<stderr>":
                stream = "ext://sys.stderr"
            elif stream_name == "<stdout>":
                stream = "ext://sys.stdout"
            else:
                stream = f"ext:{root_stream.name}"
    else:
        stream = "ext://sys.stdout"
    logging_confg = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": logging.Formatter,
                "fmt": fmt,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                # noqa: E501
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": root_handler.__class__,
                "stream": stream,
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": stream,
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default"],
                "level": getLogger("uvicorn").getEffectiveLevel(),
                # logging.getLevelName(root_logger.level),
                "propagate": False,
                # "propagate": root_logger.propagate,
            },
            "uvicorn.error": {
                "level": getLogger("uvicorn.error").getEffectiveLevel()
            },

            "uvicorn.access": {
                "handlers": ["access"],
                "level": getLogger("uvicorn.access").getEffectiveLevel(),
                "propagate": False
            },
        },
    }

    uvicorn_server = uvicorn.Server(uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        use_colors=None,
        log_config=logging_confg,
        # loop="asyncio",
    ))
    return uvicorn_server


async def sandbox_daemon(
        session_id: str,
        function_id: str,
        timeout: float,  # TODO
        args: Args,
        kwargs: Dict[str, Any],
) -> AsyncGenerator[str, None]:
    """
    This function is called by the sandbox daemon to execute a function in the sandbox.
    The code use a run_in_executor to run the function in a separate thread.
    All the stdio is captured and sent back to the client.
    The exception is also sent back to the client.
    """
    try:
        from .catch_stdio import catch_stdio, acatch_stdio
        loop = asyncio.get_event_loop()

        module_name, function_name = function_id.split(':', 1)
        module = importlib.import_module(module_name)
        try:
            function = getattr(module, function_name)
        except AttributeError:
            logger.warning("Function %s.%s() not found", module, function_name)
            return
        use_async = inspect.iscoroutinefunction(function)
        logger.debug(f"(%s) calling %s%s.%s(%s,%s)...",
                     session_id,
                     "async " if use_async else "",
                     module_name, function_name,
                     ",".join(map(repr, args)),
                     ",".join([f"{k}={repr(v)}" for k, v in kwargs.items()]))

        stdio_queue = asyncio.Queue()

        if use_async:
            async def _set_sandbox_and_catch_stdio() -> Any:
                rc = await acatch_stdio(
                    stdio_queue,
                    function, kwargs, *args)
                return rc

            fut = asyncio.create_task(_set_sandbox_and_catch_stdio(),
                                      name="catch_stdio")
        else:
            @sandbox_loop
            def _set_sandbox_and_catch_stdio():
                try:
                    set_is_in_sandbox(True)
                    return catch_stdio(
                        stdio_queue,
                        function, kwargs, *args)
                except Exception as e:
                    logger.error(traceback.format_exc())
                    raise e

            fut = loop.run_in_executor(
                None,
                _set_sandbox_and_catch_stdio,
            )
        while stdio_queue:
            msg = await stdio_queue.get()
            if "result" in msg:
                result = msg
                break
            elif "exception" in msg:
                break
            elif "stdout" in msg:
                yield _sse_msg(json.dumps(msg))
            elif "stderr" in msg:
                yield _sse_msg(json.dumps(msg))
        result = await fut
        if "result" in result:
            logger.debug("(%s) ... return %s", session_id, repr(result["result"]))
            result["result"] = to_b85(result["result"])
        if "exception" in result:
            logger.debug("(%s) ... raise %s", session_id,
                         repr(result["exception"][1]))
            result["exception"] = to_b85(result["exception"])
        yield _sse_msg(json.dumps(result))
    except CancelledError:
        logger.info("(%s) ... cancelled", session_id)
        yield json.dumps({"session_id": session_id, "cancelled": True})
    except AssertionError as e:
        logger.exception("assertion %s", traceback.format_exc())
        sys.exit(-1)
    except Exception as e:
        logger.info("(%s) ... error %s", session_id, repr(e))
        traceback.print_exception(e)
        yield json.dumps({"session_id": session_id, "error": repr(e)})


# %%

class LocalTaskDaemon(SSESandbox):

    def __init__(self, token: Optional[str] = None):
        super().__init__(token)
        self.uvicorn: Optional[Server] = None

    def update_rules(self,
                     *,
                     envs: Envs,
                     config: ConfigLines) -> AllRules:
        return config, envs, "task", [], []

    async def start(self,
                    log_level: int,
                    envs: Envs,
                    config: ConfigLines,
                    token: Optional[str]) -> None:

        loop = get_sandbox_loop()
        initial_threshold: float = loop.slow_callback_duration
        try:
            # during server launch, accept a longer delay for the async loop.
            loop.slow_callback_duration = 1.0

            self.uvicorn = create_uvicorn_daemon(self.token)

            start_event = asyncio.Event()

            async def _run_daemon():
                try:
                    start_event.set()
                    assert asyncio.get_running_loop() == get_sandbox_loop()
                    await self.uvicorn.serve()
                except asyncio.CancelledError as e:
                    if self.uvicorn:
                        try:
                            await self.uvicorn.shutdown()
                        except Exception as e:
                            logger.warning(f"Ignore error during uvicorn shutdown: {e}")
                        self.uvicorn.started = False
                except SystemExit:
                    raise

            self.task = loop.create_task(_run_daemon(), name="ServerTask")

            # Warning: the server is not yet ready to accept connections. Wait a small delay
            await start_event.wait()
            while not self.uvicorn.started:
                await asyncio.sleep(0.1)

        finally:
            loop.slow_callback_duration = initial_threshold
        logger.debug("Uvicorn started")

    async def shutdown(self) -> None:
        if not self.is_started:
            logger.warning("Server not started")
            return
        self.task.cancel()
        await self.task
        self.uvicorn = None
        self.task = None

    @property
    def is_started(self) -> bool:
        return self.uvicorn.started if self.uvicorn else False

    async def join(self) -> None:
        await self.task


async def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

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

    parser.add_argument(
        '-n', '--no-py-sandbox',
        action='store_true',
        help='Desactivate py-sandbox'
    )

    # Parse the arguments provided by the user
    args = parser.parse_args()

    # Access the value of --sandbox-provider
    outer_sandbox: Optional[str] = args.outer_sandbox
    assert outer_sandbox, "--outer-sandbox is required"
    log_level = configure_logging_level(args.verbose)

    # -------------
    # Read all configuration from stdin until EOF
    config_body = []
    token = "NO_TOKEN"
    for line in sys.stdin:
        if line == END_OF_FILE:
            token = next(sys.stdin).strip()
            break
        config_body.append(line)
    logging.debug("config body and token successfully read from stdin")

    # In this case, use the standard loop for is place of the sandbox
    set_sandbox_loop(asyncio.get_running_loop())

    if not args.no_py_sandbox:
        # Activate python sandbox
        from pysandboxes.py_sandbox import activate_sandboxes

        activate_sandboxes(dict(os.environ),
                           args_rules=None,
                           outer_sandbox=outer_sandbox,
                           config=config_body)
        logging.info(
            f"Start a py-sandbox encapsulated in an os-sandox of type '{outer_sandbox}'")
    else:
        logging.info(
            f"Start ONLY an os-sandox of type '{outer_sandbox}'")

    task_daemon = LocalTaskDaemon(token=token)
    try:
        await task_daemon.start(log_level,
                                envs=dict(os.environ),
                                config=config_body,
                                token=token)
        await task_daemon.join()
        return 0
    finally:
        await task_daemon.shutdown()


if __name__ == "__main__":
    # Kill this process when the parent is killed
    set_pdeathsig()
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
