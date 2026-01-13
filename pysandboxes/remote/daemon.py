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
from typing import AsyncGenerator, List, Any, Optional, TYPE_CHECKING
from typing import Dict

from pysandboxes.remote.manage_loop import sandbox_loop

if TYPE_CHECKING:
    import uvicorn

from fastapi import FastAPI, Request, Body
from fastapi.responses import StreamingResponse

from .base_daemon import BaseDaemon
from .parameters import HOST, PORT, PATH_RPC
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


def _sse_msg(data: str):
    return "data:" + data + "\n\n"


async def sandbox_daemon(
        token: str,  # TODO: token
        session_id: str,
        function_id: str,
        timeout: float,  # TODO
        args: List[Any],
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
                set_is_in_sandbox(True)
                rc = await acatch_stdio(
                    stdio_queue,
                    function, kwargs, *args)
                return rc

            # task = asyncio.create_task(
            #     _set_sandbox_and_catch_stdio())
            fut = asyncio.gather(_set_sandbox_and_catch_stdio())
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
            result["result"] = _to_b85(result["result"])
        if "exception" in result:
            logger.debug("(%s) ... raise %s", session_id,
                         repr(result["exception"][1]))
            result["exception"] = _to_b85(result["exception"])
        result["session_id"] = session_id
        yield _sse_msg(json.dumps(result))
    except CancelledError:
        logger.info("(%s) ... cancelled", session_id)
        yield json.dumps({"session_id": session_id, "cancelled": True})
    except AssertionError as e:
        logger.exception("assertion %s", traceback.format_exc())
        sys.exit(-1)
    except Exception as e:
        logger.info("(%s) ... error %s", session_id, repr(e))
        yield json.dumps({"session_id": session_id, "error": repr(e)})


# %%

def create_uvicorn_daemon(log_level: int) -> 'uvicorn.Server':
    import uvicorn

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
        logger.debug(f"{asyncio.get_running_loop()=} {id(asyncio.get_running_loop())}")
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

    # Extract current logging configuration
    # If not logger exist, try to duplicate the root logger parameters
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_handler = root_logger.handlers[0]
    else:
        root_handler = logging.StreamHandler(stream=sys.stderr)  # FIXME: a tester
        # root_handler=logging.StreamHandler(stream="ext://sys.stdout")  # FIXME: a tester
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
        stream = None
    default_level = logger.getEffectiveLevel()
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
                "fmt": '%(levelname)s:%(name)s: %(client_addr)s - '
                       '"%(request_line)s" %(status_code)s',
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
                "level": logging.ERROR,  # logging.getLevelName(root_logger.level),
                "propagate": False,
                # "propagate": root_logger.propagate,
            },
            "uvicorn.error": {
                "level": default_level
            },
            "uvicorn.access": {
                "handlers": ["access"],
                "level": default_level,
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
    ))
    return uvicorn_server


class LocalTaskDaemon(BaseDaemon):

    async def start(self, log_level: int, envs: dict[str, str] = None) -> Any:
        if not envs:
            envs = dict(os.environ)
        set_is_in_sandbox(True)

        self.uvicorn = create_uvicorn_daemon(log_level)

        start_event = asyncio.Event()

        async def _run_daemon():
            try:
                start_event.set()
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

        self.task = asyncio.create_task(_run_daemon(), name="ServerTask")

        # Warning: the server is not yet ready to accept connections. Wait a small delay
        await start_event.wait()
        while not self.uvicorn.started:
            await asyncio.sleep(0)
        assert is_in_sandbox()  # FIXME: a garder ?
        logger.debug("Uvicorn started")

    async def shutdown(self) -> None:
        if not self.is_started:
            raise RuntimeError("Server not started")
        self.task.cancel()
        await self.task
        self.uvicorn= None
        self.task = None

    @property
    def is_started(self) -> bool:
        return self.uvicorn.started if self.uvicorn else False

    async def join(self) -> None:
        await self.task


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
    task_daemon = LocalTaskDaemon()
    try:
        await task_daemon.start(log_level)
        await task_daemon.join()
    finally:
        await task_daemon.shutdown()


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
