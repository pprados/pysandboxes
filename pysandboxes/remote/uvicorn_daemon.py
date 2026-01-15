#!/usr/bin/env python3
import asyncio
import logging
import sys
from logging import getLogger
from typing import TYPE_CHECKING

from .daemon import RPCPayload, sandbox_daemon
from .os_sandboxes import get_token

if TYPE_CHECKING:
    import uvicorn

from fastapi import FastAPI, Request, Body, HTTPException
from fastapi.responses import StreamingResponse

from .parameters import HOST, PORT, PATH_RPC
from .tools import _from_b85, is_in_sandbox, set_is_in_sandbox
from tblib import pickling_support

pickling_support.install()

logger = logging.getLogger(__name__)

def create_uvicorn_daemon(token:str) -> 'uvicorn.Server':
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
                _from_b85(payload.args),
                _from_b85(payload.kwargs),
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
                "level": getLogger("uvicorn").getEffectiveLevel(),  # logging.getLevelName(root_logger.level),
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
    ))
    return uvicorn_server
