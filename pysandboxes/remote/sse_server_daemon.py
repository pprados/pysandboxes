import asyncio
import base64
import importlib
import inspect
import json
import logging
import sys
import traceback
from asyncio import CancelledError
from dataclasses import dataclass
from logging import getLogger
from typing import AsyncGenerator, Any, Optional
from typing import Dict

from uvicorn import Server

from .parameters import TIMEOUT_GRACEFUL_SHUTDOWN, POLLING_DELAY, \
    TIMEOUT_FOR_STOP_DAEMON, MAX_CONNECT_RETRY
from .sse_base_daemon import BaseSSESandbox
from .tools import from_b85, to_b85
from ..all_rules import AllRules
from ..private_loop import sandbox_loop, get_sandbox_loop
from ..sb_types import Args, Envs
from ..tools import set_is_in_sandbox, SyncOrAsyncFunc

logger = logging.getLogger(__name__)

_active_requests = 0


@dataclass
class RPCPayload(object):
    session_id: str
    function: str
    args: str
    kwargs: str


def _sse_msg(data: str):
    return "data:" + data + "\n\n"


async def sandbox_daemon(
        session_id: str,
        function_id: str,
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

    global _active_requests
    try:
        _active_requests += 1

        loop = asyncio.get_event_loop()

        module_name, function_name = function_id.split(':', 1)
        set_is_in_sandbox(True)
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
        logger.exception("assertion %s", traceback.format_exc())
        sys.exit(-1)
        # Ignore?
    except Exception as e:
        logger.exception("(%s) ... error %s", session_id, repr(e))
        yield json.dumps({"session_id": session_id, "error": repr(e)})
    finally:
        _active_requests -= 1
        set_is_in_sandbox(False)


def create_uvicorn_daemon(token: str,
                          host: str,
                          port: int) -> 'uvicorn.Server':
    import uvicorn

    from fastapi import FastAPI, Request, Body, HTTPException
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    active_requests = 0

    @app.get("/ping")
    async def ping(
    ):
        return {"message": "OK"}

    @app.post("/rpc")
    async def rpc_endpoint(
            request: Request,
            payload: RPCPayload = Body(...,
                                       description="Payload containing code and authentication token.")
    ) -> StreamingResponse:
        """
        SSE endpoint to process a given code string, authenticated by a token,
        and stream back structured results (stdout, stderr, result).
        """
        from ..os_sandbox import is_accept_incoming_call

        # logger.debug(request.headers["Authorization"])
        if ("Authorization" not in request.headers or
                request.headers["Authorization"] != f"Bearer {token}"):
            logger.error(
                "Invalid token")
            raise HTTPException(status_code=401, detail="Invalid token")
        if not is_accept_incoming_call():
            raise HTTPException(status_code=503,
                                detail="The sandbox demon is being stopped.")
        # Pass the code and authenticated user_id to the event generator
        return StreamingResponse(
            sandbox_daemon(
                payload.session_id,
                payload.function,
                from_b85(payload.args),
                from_b85(payload.kwargs),
            ),
            media_type="text/event-stream"
        )

    # TODO: Use https
    # Extract current logging configuration
    # If not logger exist, try to duplicate the root logger parameters
    uvicorn_logger = logging.getLogger("uvicorn")
    if uvicorn_logger.handlers:
        root_handler = uvicorn_logger.handlers[0]
    else:
        root_handler = logging.StreamHandler(stream=sys.stdout)

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
                "level": uvicorn_logger.getEffectiveLevel(),
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
        host=host,
        port=port,
        use_colors=None,
        log_config=logging_confg,
        access_log=True,
        timeout_graceful_shutdown=TIMEOUT_GRACEFUL_SHUTDOWN,
    ))
    return uvicorn_server


class SSEServerDaemon(BaseSSESandbox):
    __slots__ = ("uvicorn", "task", "port", "hostname", "stopped")

    def __init__(self, token: str, *, port: int):
        super().__init__(token, host="localhost", max_connect_retry=MAX_CONNECT_RETRY)
        self.uvicorn: Optional[Server] = None
        self.task = None
        self.port = port
        self.hostname = "localhost"
        self.stopped = True

    @property
    def active_request(self) -> int:
        global _active_request
        return _active_request

    def update_rules(self,
                     *,
                     envs: Envs,
                     all_rules: AllRules) -> AllRules:
        return AllRules(config=(),
                        envs=envs,
                        os_sandbox="",
                        use_py_sandbox=all_rules.use_py_sandbox,
                        learning_path=all_rules.learning_path,
                        learn=all_rules.learn,
                        envs_rules=(),
                        socket_rules=all_rules.socket_rules,
                        file_rules=all_rules.file_rules,
                        )

    async def start(self,
                    all_rules: AllRules,
                    *,
                    envs: Dict[str, str],
                    log_level: int,
                    init_fn: Optional[SyncOrAsyncFunc],
                    ) -> None:

        set_is_in_sandbox(True)
        if init_fn:
            if asyncio.iscoroutinefunction(init_fn):
                await init_fn()
            else:
                init_fn()
        loop = get_sandbox_loop()
        initial_threshold: float = loop.slow_callback_duration
        try:
            # during server launch, accept a longer delay for the async loop.
            loop.slow_callback_duration = 1.0
            self.uvicorn = create_uvicorn_daemon(self.token,
                                                 self.hostname,
                                                 self.port)

            start_event = asyncio.Event()

            async def _run_daemon():
                try:
                    start_event.set()
                    assert asyncio.get_running_loop() == get_sandbox_loop()
                    await self.uvicorn.serve()
                except asyncio.CancelledError as e:
                    # logger.debug("Receive cancel server")
                    self._accept_incoming = False
                    if self.uvicorn:
                        try:
                            await asyncio.wait_for(
                                self.uvicorn.shutdown(),
                                timeout=TIMEOUT_GRACEFUL_SHUTDOWN,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"Timeout during uvicorn daemon_shutdown. Force exit")
                            self.uvicorn.force_exit = True
                        self.uvicorn.started = False
                except SystemExit:
                    raise

            self.task = loop.create_task(_run_daemon(), name="ServerTask")

            await start_event.wait()
            while not self.uvicorn.started:
                await asyncio.sleep(POLLING_DELAY)
            self._accept_incoming = True
            self.stopped = False
            logger.debug("Uvicorn started")
        finally:
            loop.slow_callback_duration = initial_threshold

    async def stop(self, max_pending: int) -> None:
        """ End all current jobs """
        set_is_in_sandbox(False)
        logger.debug("Remote daemon_shutdown calling")
        if not self.is_started:
            logger.warning("Server not started")
            return
        if self.stopped:
            return
        self._accept_incoming = False
        logger.debug("Refuse new incoming call")
        # wait for task completed
        global _active_requests
        start_time = asyncio.get_event_loop().time()
        while _active_requests > max_pending:
            if ((asyncio.get_event_loop().time() - start_time) >=
                    TIMEOUT_FOR_STOP_DAEMON):
                logger.info("Impossible to stop %i current request",
                            _active_requests - max_pending)
                break
            await asyncio.sleep(POLLING_DELAY)
        logger.debug("All request are complete")
        self.stopped = True

    async def shutdown(self, graceful_shutdown: bool = True) -> None:
        logger.debug("SSEServerDaemon.shutdown()")
        await self.stop(max_pending=0)
        self.task.cancel()
        await self.task
        self.uvicorn = None
        self.task = None
        logger.debug("Remote shutdowned")

    @property
    def is_started(self) -> bool:
        return self.uvicorn.started if self.uvicorn else False

    async def join(self) -> None:
        await self.task
