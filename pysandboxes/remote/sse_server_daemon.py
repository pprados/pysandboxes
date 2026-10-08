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
import hmac
import importlib
import inspect
import json
import logging
import sys
import traceback
from asyncio import CancelledError, Task
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Any, AsyncGenerator

from uvicorn import Server

from ..all_rules import AllRules
from ..e import sandbox_denials
from ..guard_import import framework_imports, user_code
from ..immutable_dict import ImmutableDict
from ..lifecycle import arm
from ..private_loop import get_sandbox_loop
from ..sb_types import Args, Envs
from ..tools import (
    Environ,
    SyncOrAsyncFunc,
    set_is_in_sandbox,
)
from .base_sse_daemon import BaseSSESandbox
from .parameters import (
    MAX_CONNECT_RETRY,
    POLLING_DELAY,
    TIMEOUT_FOR_STOP_DAEMON,
    TIMEOUT_GRACEFUL_SHUTDOWN,
)
from .tools import check_sse_line, describe_exception, from_b85, result_requires_objects, to_b85

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
        # set_is_in_sandbox(True)
        try:
            # Function_id supplied by the trusted parent process
            with user_code():
                module = importlib.import_module(module_name)
            function = getattr(module, function_name)
        except ModuleNotFoundError as e:
            logger.error("Module %s not found", module_name)
            raise ValueError(f"Module {module_name} not found") from e
        except AttributeError as e:
            logger.error("Function %s.%s() not found", module_name, function_name)
            raise ValueError(f"Function {module_name}.{function_name}() not found") from e
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

        async def _async_set_sandbox_and_catch_stdio() -> Any:
            from .catch_stdio import acatch_stdio

            rc = await acatch_stdio(stdio_queue, function, kwargs, *args)
            return rc

        async_fut = asyncio.create_task(_async_set_sandbox_and_catch_stdio(), name="catch_stdio")
        # A task ending without posting its outcome (cancelled) must not leave this loop waiting forever.
        async_fut.add_done_callback(lambda _: stdio_queue.put_nowait({"done": True}))
        while stdio_queue:
            msg = await stdio_queue.get()
            if "result" in msg:
                result = msg
                break
            elif "exception" in msg or "done" in msg:
                break
            elif "stdout" in msg:
                yield _sse_msg(json.dumps(msg))
            elif "stderr" in msg:
                yield _sse_msg(json.dumps(msg))
        result = await async_fut
        if "result" in result:
            logger.debug("(%s) ... return %s", session_id, repr(result["result"])[:40])
            result["result"] = to_b85(result["result"])
            from ..learning import add_learning_rule, is_learning_mode

            if is_learning_mode():
                mode = "objects" if result_requires_objects(result["result"]) else "data-only"
                add_learning_rule(f"remote-result-mode={mode}")
        if "exception" in result:
            logger.debug("(%s) ... raise %s", session_id, repr(result["exception"]))
            exception, serial_traceback = result["exception"]
            traceback.print_exception(exception)
            # Two forms of the same exception. The parent tries the rich one
            # under the transport guard and falls back to the descriptor when
            # the guard refuses it -- an exception's state routinely holds
            # objects the guard cannot admit (httpx.Request, Path, application
            # objects), and losing the refusal itself would be worse than
            # losing those attributes.
            result["exception_fallback"] = base64.b85encode(
                # serialization only
                pickle.dumps(
                    (describe_exception(exception, sandbox_denials(exception)), serial_traceback),
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            ).decode("utf-8")
            try:
                result["exception"] = base64.b85encode(
                    # serialization only
                    pickle.dumps(result["exception"], protocol=pickle.HIGHEST_PROTOCOL)
                ).decode("utf-8")
            except Exception as exc:  # pragma: no cover - depends on the payload
                # An unpicklable member of the exception's state used to sink
                # the whole reply; the descriptor still carries the refusal.
                logger.debug("(%s) ... exception not picklable: %s", session_id, exc)
                result["exception"] = ""
        # Checked before sending: an oversized line dies in the parent's HTTP
        # reader, naming nothing. Raising here reaches the caller as a refusal
        # that says what was too big (the except clause below carries it).
        reply = _sse_msg(json.dumps(result))
        check_sse_line(reply)
        yield reply
    except CancelledError:
        logger.info("(%s) ... cancelled", session_id)
        yield _sse_msg(json.dumps({"session_id": session_id, "cancelled": True}))
    except AssertionError:
        logger.exception("assertion %s", traceback.format_exc())
        sys.exit(-1)
        # Ignore?
    except Exception as e:
        logger.exception("(%s) ... error %s", session_id, repr(e))
        yield _sse_msg(json.dumps({"session_id": session_id, "error": repr(e)}))
    finally:
        _active_requests -= 1


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
        payload: RPCPayload = Body(..., description="Payload containing code and authentication token."),  # noqa: B008
    ) -> StreamingResponse:
        """
        SSE endpoint to process a given code string, authenticated by a token,
        and stream back structured results (stdout, stderr, result).
        """
        from .._os_sandbox import is_accept_incoming_call

        # logger.debug(request.headers["Authorization"])
        # Constant-time comparison: `!=` stops at the first differing byte, so its timing would leak how much of
        # the token a guess got right. Bytes, because compare_digest refuses a str holding a non-ASCII character.
        authorization = request.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(authorization, f"Bearer {token}".encode()):
            logger.error("Invalid token")
            raise HTTPException(status_code=401, detail="Invalid token")
        if not is_accept_incoming_call():
            raise HTTPException(status_code=503, detail="The sandbox daemon is being stopped.")
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
        # stderr: the child inherits the caller's stdout, which an MCP server on a stdio transport reads
        # as JSON-RPC, and an "ERROR:uvicorn.error:..." line there broke it.
        root_handler = logging.StreamHandler(stream=sys.stderr)

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
            stream = "ext://sys.stderr"
    else:
        stream = "ext://sys.stderr"
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
                "fmt": "%(levelprefix)s %(client_addr)s - " '"%(request_line)s" %(status_code)s',
                # noqa: E501
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": ".".join([root_handler.__module__, root_handler.__class__.__qualname__]),
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

    __slots__ = ("uvicorn", "task", "port", "bind_host", "stopped")

    def __init__(self, token: str, *, port: int, bind_host: str = "127.0.0.1"):
        """Initialize SSE server daemon.

        Args:
            token: Authentication token for API access.
            port: Port number for HTTP server.
            bind_host: Address the HTTP server listens on (see ``DaemonParameters.bind_host``).
        """
        super().__init__(token, max_connect_retry=MAX_CONNECT_RETRY)
        self.uvicorn: Server | None = None
        self.task: Task | None = None
        self.port = port
        self.bind_host = bind_host
        self.stopped = True

    @property
    def active_request(self) -> int:
        """Get number of currently active requests.

        Returns:
            Number of requests being processed.
        """
        global _active_requests
        return _active_requests

    def update_rules_and_activate(
        self,
        *,
        envs: Envs,
        all_rules: AllRules,
        temp: Path,
    ) -> AllRules:
        """Update security rules for server daemon.

        Args:
            envs: Environment variables.
            all_rules: Current security rules.
            temp: Run-time directory shared with the sandbox. Accepted for the
                `BaseDaemon` signature; the rebuilt rules do not use it.

        Returns:
            Updated security rules for server context.
        """
        return AllRules(
            root_path=all_rules.root_path,
            config=[],
            envs=envs,
            os_sandbox="",
            os_sandbox_params=ImmutableDict({}),
            use_py_sandbox=all_rules.use_py_sandbox,
            port=all_rules.port,
            learning_path=all_rules.learning_path,
            learn=all_rules.learn,
            remote_result_guard=all_rules.remote_result_guard,
            remote_result_data_only=all_rules.remote_result_data_only,
            envs_rules=(),
            socket_rules=all_rules.socket_rules,
            pin_dns=all_rules.pin_dns,
            file_rules=all_rules.file_rules,
            import_rules=all_rules.import_rules,
            api_rules=all_rules.api_rules,
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
            with user_code():
                if asyncio.iscoroutinefunction(init_fn):
                    await init_fn()
                else:
                    init_fn()
        logging.basicConfig(level=logging.INFO)  # Set logs if it's not already set by init_fn()
        loop = get_sandbox_loop()
        initial_threshold: float = loop.slow_callback_duration
        try:
            # during server launch, accept a longer delay for the async loop.
            loop.slow_callback_duration = 1.0
            with framework_imports():
                self.uvicorn = create_uvicorn_daemon(self.token, self.bind_host, self.port)
                # starlette resolves anyio's backend on each request, which imports it lazily.
                importlib.import_module("anyio._backends._asyncio")

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
                            logger.warning("Timeout during uvicorn daemon_shutdown. Force exit")
                            self.uvicorn.force_exit = True
                        self.uvicorn.started = False
                except SystemExit:
                    raise

            # uvicorn loads its protocol and lifespan modules while it starts: framework
            # imports, closed before the first request is accepted.
            with framework_imports():
                self.task = loop.create_task(_run_daemon(), name="ServerTask")

                await start_event.wait()
                while self.uvicorn and not self.uvicorn.started:
                    await asyncio.sleep(POLLING_DELAY)
            self._accept_incoming = True
            self.stopped = False
            logger.debug("Uvicorn started")
            # Arm once the server is up, not on every incoming call: init_fn
            # and the uvicorn setup are framework code and must run disarmed.
            # What follows is the serve loop and the calls it dispatches, which
            # the previous per-request arm() already ran armed from the second
            # request on; the only behaviour that changes is a daemon serving
            # no request at all, which now serves and shuts down armed.
            arm()
        finally:
            loop.slow_callback_duration = initial_threshold

    async def _stop(self, max_pending: int) -> None:
        """Stop server and wait for pending requests to complete.

        Args:
            max_pending: Maximum number of pending requests to wait for.
        """
        logger.debug("Remote daemon_shutdown calling")
        # set_is_in_sandbox(False)
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
            if (asyncio.get_event_loop().time() - start_time) >= TIMEOUT_FOR_STOP_DAEMON:
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
        set_is_in_sandbox(False)
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
