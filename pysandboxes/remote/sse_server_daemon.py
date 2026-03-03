# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Server-Sent Events (SSE) server daemon for PySandboxes remote execution.

This module implements the server-side component of PySandboxes remote execution
using FastAPI and Uvicorn. It provides a secure HTTP API for executing code
in sandboxed environments with real-time streaming of stdout/stderr.

Key components:
- RPCPayload: Data structure for remote procedure calls
- sandbox_daemon: Core execution engine with stdio capture
- SSEServerDaemon: Main server implementation
- Authentication and authorization via Bearer tokens
"""

import asyncio
import base64
import importlib
import inspect
import json
import logging
import sys
import traceback
from asyncio import CancelledError, Task
from dataclasses import dataclass
from logging import getLogger
from typing import Any, AsyncGenerator

from uvicorn import Server

from ..all_rules import AllRules
from ..private_loop import get_sandbox_loop
from ..sb_types import Args, Envs
from ..tools import (
    Environ,
    SyncOrAsyncFunc,
    set_is_in_sandbox,
)
from .parameters import (
    MAX_CONNECT_RETRY,
    POLLING_DELAY,
    TIMEOUT_FOR_STOP_DAEMON,
    TIMEOUT_GRACEFUL_SHUTDOWN,
)
from .sse_base_daemon import BaseSSESandbox
from .tools import from_b85, to_b85

logger = logging.getLogger(__name__)

_active_requests = 0


@dataclass
class RPCPayload(object):
    """Payload structure for remote procedure calls.

    Attributes:
        session_id: Unique identifier for the execution session.
        function: Module and function name in format 'module:function'.
        args: Base85-encoded serialized positional arguments.
        kwargs: Base85-encoded serialized keyword arguments.
    """

    session_id: str
    function: str
    args: str
    kwargs: str


def _sse_msg(data: str) -> str:
    """Format data as Server-Sent Events message.

    Args:
        data: JSON string to send as SSE message.

    Returns:
        Properly formatted SSE message string.
    """
    return "data:" + data + "\n\n"


async def sandbox_daemon(
    session_id: str,
    function_id: str,
    args: Args,
    kwargs: dict[str, Any],
) -> AsyncGenerator[str, None]:
    """Execute function in sandbox with stdio capture and streaming.

    Args:
        session_id: Unique session identifier for tracking.
        function_id: Function identifier in 'module:function' format.
        args: Positional arguments for function call.
        kwargs: Keyword arguments for function call.

    Yields:
        SSE-formatted messages containing stdout, stderr, result, or exception.
    """
    import pickle

    global _active_requests
    try:
        _active_requests += 1

        module_name, function_name = function_id.split(":", 1)
        set_is_in_sandbox(True)
        try:
            module = importlib.import_module(module_name)
            function = getattr(module, function_name)
        except ModuleNotFoundError:
            logger.error("Module %s not found", module_name)
            raise ValueError(f"Module {module_name} not found")
        except AttributeError:
            logger.error("Function %s.%s() not found", module_name, function_name)
            raise ValueError(f"Function {module_name}.{function_name}() not found")
        use_async = inspect.iscoroutinefunction(function)
        logger.debug(
            "(%s) calling %s%s.%s(%s,%s)...",
            session_id,
            "async " if use_async else "",
            module_name,
            function_name,
            ",".join(map(repr, args)),
            ",".join([f"{k}={repr(v)}" for k, v in kwargs.items()]),
        )

        stdio_queue: asyncio.Queue = asyncio.Queue()
        async_fut: asyncio.Future | None = None

        async def _async_set_sandbox_and_catch_stdio() -> Any:
            from .catch_stdio import acatch_stdio

            rc = await acatch_stdio(stdio_queue, function, kwargs, *args)
            return rc

        async_fut = asyncio.create_task(
            _async_set_sandbox_and_catch_stdio(), name="catch_stdio"
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
        result = await async_fut
        if "result" in result:
            logger.debug("(%s) ... return %s", session_id, repr(result["result"]))
            result["result"] = to_b85(result["result"])
        if "exception" in result:
            logger.debug("(%s) ... raise %s", session_id, repr(result["exception"]))
            traceback.print_exception(result["exception"][0])
            result["exception"] = base64.b85encode(
                pickle.dumps(result["exception"], protocol=pickle.HIGHEST_PROTOCOL)
            ).decode("utf-8")
        yield _sse_msg(json.dumps(result))
    except CancelledError:
        logger.info("(%s) ... cancelled", session_id)
        yield json.dumps({"session_id": session_id, "cancelled": True})
    except AssertionError:
        logger.exception("assertion %s", traceback.format_exc())
        sys.exit(-1)
        # Ignore?
    except Exception as e:
        logger.exception("(%s) ... error %s", session_id, repr(e))
        yield json.dumps({"session_id": session_id, "error": repr(e)})
    finally:
        _active_requests -= 1
        set_is_in_sandbox(False)


def create_uvicorn_daemon(token: str, host: str, port: int) -> Server:
    """Create configured Uvicorn server for sandbox daemon.

    Args:
        token: Authentication token for API access.
        host: Host address to bind to.
        port: Port number to listen on.

    Returns:
        Configured Uvicorn server instance.
    """
    import uvicorn
    from fastapi import Body, FastAPI, HTTPException, Request
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"message": "OK"}

    @app.post("/rpc")
    async def rpc_endpoint(
        request: Request,
        payload: RPCPayload = Body(
            ..., description="Payload containing code and authentication token."
        ),
    ) -> StreamingResponse:
        """
        SSE endpoint to process a given code string, authenticated by a token,
        and stream back structured results (stdout, stderr, result).
        """
        from ..os_sandbox import is_accept_incoming_call

        # logger.debug(request.headers["Authorization"])
        if (
            "Authorization" not in request.headers
            or request.headers["Authorization"] != f"Bearer {token}"
        ):
            logger.error("Invalid token")
            raise HTTPException(status_code=401, detail="Invalid token")
        if not is_accept_incoming_call():
            raise HTTPException(
                status_code=503, detail="The sandbox demon is being stopped."
            )
        # Pass the code and authenticated user_id to the event generator
        return StreamingResponse(
            sandbox_daemon(
                payload.session_id,
                payload.function,
                from_b85(payload.args),
                from_b85(payload.kwargs),
            ),
            media_type="text/event-stream",
        )

    # Extract current logging configuration
    # If not logger exist, try to duplicate the root logger parameters
    uvicorn_logger = logging.getLogger("uvicorn")
    if uvicorn_logger.handlers:
        root_handler = uvicorn_logger.handlers[0]
    else:
        root_handler = logging.StreamHandler(stream=sys.stdout)

    fmt = getattr(root_handler.formatter, "_fmt", "%(levelname)s:%(name)s:%(message)s")
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
                "fmt": "%(levelprefix)s %(client_addr)s - "
                '"%(request_line)s" %(status_code)s',
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
            "uvicorn.error": {"level": getLogger("uvicorn.error").getEffectiveLevel()},
            "uvicorn.access": {
                "handlers": ["access"],
                "level": getLogger("uvicorn.access").getEffectiveLevel(),
                "propagate": False,
            },
        },
    }

    uvicorn_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            use_colors=None,
            log_config=logging_confg,
            access_log=True,
            timeout_graceful_shutdown=TIMEOUT_GRACEFUL_SHUTDOWN,
        )
    )
    return uvicorn_server


class SSEServerDaemon(BaseSSESandbox):
    """Server-side daemon for handling sandboxed code execution.

    Provides HTTP API endpoints for remote code execution with real-time
    streaming of output via Server-Sent Events.
    """

    __slots__ = ("uvicorn", "task", "port", "hostname", "stopped")

    def __init__(self, token: str, *, port: int):
        """Initialize SSE server daemon.

        Args:
            token: Authentication token for API access.
            port: Port number for HTTP server.
        """
        super().__init__(token, host="localhost", max_connect_retry=MAX_CONNECT_RETRY)
        self.uvicorn: Server | None = None
        self.task: Task | None = None
        self.port = port
        self.hostname = "localhost"
        self.stopped = True

    @property
    def active_request(self) -> int:
        """Get number of currently active requests.

        Returns:
            Number of requests being processed.
        """
        global _active_requests
        return _active_requests

    def update_rules(self, *, envs: Envs, all_rules: AllRules) -> AllRules:
        """Update security rules for server daemon.

        Args:
            envs: Environment variables.
            all_rules: Current security rules.

        Returns:
            Updated security rules for server context.
        """
        return AllRules(
            root_path=all_rules.root_path,
            config=[],  # FIXME: a quoi sert config?
            envs=envs,
            os_sandbox="",
            use_py_sandbox=all_rules.use_py_sandbox,
            learning_path=all_rules.learning_path,
            learn=all_rules.learn,
            envs_rules=(),
            socket_rules=all_rules.socket_rules,
            file_rules=all_rules.file_rules,
            import_rules=all_rules.import_rules,
        )

    async def _start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Start the SSE server daemon.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            log_level: Logging level.
            init_fn: Optional initialization function.
        """
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
            self.uvicorn = create_uvicorn_daemon(self.token, self.hostname, self.port)

            start_event = asyncio.Event()

            async def _run_daemon() -> None:
                if not self.uvicorn:
                    logger.warning("Uvicorn server not started")
                    return
                try:
                    start_event.set()
                    assert asyncio.get_running_loop() == get_sandbox_loop()
                    await self.uvicorn.serve()
                except asyncio.CancelledError:
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
                                "Timeout during uvicorn daemon_shutdown. Force exit"
                            )
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

    async def _stop(self, max_pending: int) -> None:
        """Stop server and wait for pending requests to complete.

        Args:
            max_pending: Maximum number of pending requests to wait for.
        """
        logger.debug("Remote daemon_shutdown calling")
        set_is_in_sandbox(False)
        logger.debug("Refuse new incoming call")
        self._accept_incoming = False
        if not self.is_started:
            logger.warning("Server not started")
            return
        if self.stopped:
            return
        # wait for task completed
        global _active_requests
        start_time = asyncio.get_event_loop().time()
        while _active_requests > max_pending:
            if (
                asyncio.get_event_loop().time() - start_time
            ) >= TIMEOUT_FOR_STOP_DAEMON:
                logger.info(
                    "Impossible to _stop %i current request",
                    _active_requests - max_pending,
                )
                break
            await asyncio.sleep(POLLING_DELAY)
        logger.debug("All request are complete")
        self.stopped = True

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        """Shutdown the SSE server daemon.

        Args:
            graceful_shutdown: Whether to perform graceful shutdown.
        """
        logger.debug("SSEServerDaemon._shutdown()")
        await self._stop(max_pending=0)
        if self.task:
            self.task.cancel()
            await self.task
            self.task = None
        self.uvicorn = None
        logger.debug("Remote shutdowned")

    @property
    def is_started(self) -> bool:
        """Check if server is started and ready.

        Returns:
            True if server is started, False otherwise.
        """
        return self.uvicorn.started if self.uvicorn else False

    async def join(self) -> None:
        """Wait for server task to complete.

        Raises:
            AssertionError: If server task is not available.
        """
        assert self.task
        await self.task
