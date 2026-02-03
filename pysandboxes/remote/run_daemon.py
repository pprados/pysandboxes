#!/usr/bin/env python3
import argparse
import asyncio
import base64
import importlib
import inspect
import json
import logging
import os
import pickle
import sys
import traceback
from asyncio import CancelledError
from dataclasses import dataclass
from logging import getLogger
from typing import AsyncGenerator, Any, Optional
from typing import Dict

from tblib import pickling_support
from uvicorn import Server

from pysandboxes.learning import is_learning_mode, generate_config_from_learning
from pysandboxes.main_logger import pysandboxes_logger
from pysandboxes.remote.subprocess_daemon import SubProcessParameters
from .parameters import PATH_RPC, HOST, PORT
from .sse_sandbox import SSESandbox
from .tools import configure_logging_level, \
    set_pdeathsig
from ..private_loop import sandbox_loop, get_sandbox_loop, set_sandbox_loop
from ..py_sandbox import AllRules
from ..tools import set_is_in_sandbox, is_in_sandbox, SyncOrAsyncFunc
from ..types import Args, Envs

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

    @app.get("/ping")
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
        import pickle
        def from_b85(b85: str) -> Any:
            return pickle.loads(
                base64.b85decode(b85.encode("utf-8")),
            )
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
    uvicorn_logger = logging.getLogger("uvicorn")
    if uvicorn_logger.handlers:
        root_handler = uvicorn_logger.handlers[0]
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
                "propagate": False,
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
    import pickle

    def to_b85(obj: Any) -> str:
            return base64.b85encode(pickle.dumps(obj,
                                       protocol=pickle.HIGHEST_PROTOCOL
                                       )).decode("utf-8")

    # def from_b85(b85: str) -> Any:
    #     return pickle.loads(
    #         base64.b85decode(b85.encode("utf-8")),
    #     )

    try:
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
                from .catch_stdio import catch_stdio, acatch_stdio
                # TODO: vérifier pourquoi c'est différent que l'async
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
                    import os
                    logger.debug(f"{type(os.environ)=}")  # FIXME: recherche bug
                    set_is_in_sandbox(True)
                    from .catch_stdio import catch_stdio, acatch_stdio
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
                         repr(result["exception"]))
            traceback.print_exception(result["exception"][0])
            result["exception"] = base64.b85encode(pickle.dumps(result["exception"],
                                                     protocol=pickle.HIGHEST_PROTOCOL
                                                     )).decode("utf-8")
        yield _sse_msg(json.dumps(result))
    except CancelledError:
        logger.info("(%s) ... cancelled", session_id)
        yield json.dumps({"session_id": session_id, "cancelled": True})
    except AssertionError as e:
        logger.error("-------------------")
        traceback.print_exc()
        logger.error("-------------------")
        logger.exception("assertion %s", traceback.format_exc())
        sys.exit(-1)
        # Ignore?
    except Exception as e:
        logger.info("(%s) ... error %s", session_id, repr(e))
        traceback.print_exception(e)
        yield json.dumps({"session_id": session_id, "error": repr(e)})


# %%

class LocalTaskDaemon(SSESandbox):

    def __init__(self, token: str):
        super().__init__(token)
        self.uvicorn: Optional[Server] = None

    def update_rules(self,
                     *,
                     envs: Envs,
                     all_rules: AllRules) -> AllRules:
        return AllRules(config=[],
                        envs=envs,
                        os_sandbox="",
                        use_py_sandbox=all_rules.use_py_sandbox,
                        learning_path=all_rules.learning_path,
                        envs_rules=[],
                        socket_rules=[],  # FIXME: nécessiare la recopue légère ?
                        file_rules=[],
                        )

    async def start(self,
                    all_rules: AllRules,
                    *,
                    log_level: int,
                    envs: Optional[Envs],
                    init_fn: Optional[SyncOrAsyncFunc],
                    ) -> None:

        if envs is None:
            envs = os.environ
        if init_fn:
            init_fn()
        loop = get_sandbox_loop()
        initial_threshold: float = loop.slow_callback_duration
        try:
            # during server launch, accept a longer delay for the async loop.
            loop.slow_callback_duration = 1.0
            set_is_in_sandbox(True)
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
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

    parser = argparse.ArgumentParser(
        description="Start a Python-sandbox daemon inside os-sandbox."
    )

    # Add the verbose argument.
    # action='count' is key here: it counts how many times the argument is present.
    parser.add_argument(
        '-v', '--verbose',
        action='count',
        default=0,  # Default value if no -v is provided
        help='Increase output verbosity. '
             'Use '
             '-v for WARNING, '
             '-vv for INFO, '
             '-vvv for DEBUG, '
             '-vvvv for all messages.'
    )

    # Parse the arguments provided by the user
    args = parser.parse_args()

    log_level = configure_logging_level(args.verbose)

    # -------------
    # Read all configuration from stdin until EOF
    def from_b85(b85: str) -> Any:
        return pickle.loads(
            base64.b85decode(b85.encode("utf-8")),
        )

    config_body = None
    process_config: Optional[SubProcessParameters] = None
    for line in sys.stdin:
        process_config = from_b85(line.strip())
        break
    if not process_config:
        raise RuntimeError("Impossible to read the config body from stdin")
    logger.debug("config body and token successfully read from stdin")

    # Adjuste the root log level
    logging.getLogger().setLevel(log_level)

    all_rules = process_config.all_rules
    os_sandbox = all_rules.os_sandbox
    use_py_sandbox = all_rules.use_py_sandbox

    # In this case, use the standard loop in place of the private sandbox loop
    set_sandbox_loop(asyncio.get_running_loop())

    if use_py_sandbox:
        # Activate python sandbox
        from pysandboxes.py_sandbox import activate_sandboxes

        activate_sandboxes(
            all_rules,
            dict(os.environ)
        )
        pysandboxes_logger.info(
            f"Start a py-sandbox encapsulated in an os-sandox of type '{os_sandbox}'")
    else:
        pysandboxes_logger.info(
            f"Start ONLY an os-sandox of type '{os_sandbox}'")

    # Call init function
    # Note: the init_function is called AFTER the activation of the python sandbox
    init_fn: Optional[SyncOrAsyncFunc] = None
    if process_config.init_fn:
        module_name, function_name = process_config.init_fn.split(':', 1)
        module = importlib.import_module(module_name)
        init_fn = getattr(module, function_name)

    # Start the daemon
    task_daemon = LocalTaskDaemon(process_config.token)
    try:
        await task_daemon.start(
            all_rules=all_rules,
            log_level=log_level,
            envs=None,
            init_fn=init_fn,
        )
        await task_daemon.join()
        return 0
    finally:
        await task_daemon.shutdown()


def shutdown():
    logger.info("Shutting down... the daemon")
    if is_learning_mode():
        generate_config_from_learning()


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
