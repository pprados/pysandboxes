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
from typing import AsyncGenerator, List, Any, Optional
from typing import Dict

from tblib import pickling_support
from uvicorn import Server

from ..guard_sandbox import AllRules
from . import ConfigLines, Args, Envs
from .sse_sandbox import SSESandbox
from .manage_loop import sandbox_loop
from .tools import _to_b85, set_is_in_sandbox, configure_logging_level, END_OF_FILE

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

            fut = asyncio.create_task(_set_sandbox_and_catch_stdio())
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
        from .uvicorn_daemon import create_uvicorn_daemon

        self.uvicorn = create_uvicorn_daemon(self.token)

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
            await asyncio.sleep(0.1)  # FIXME
        # assert is_in_sandbox()  # FIXME: a garder ?

        logger.debug("Uvicorn started")

    async def shutdown(self) -> None:
        if not self.is_started:
            raise RuntimeError("Server not started")
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

    if not args.no_py_sandbox:
        from pysandboxes import activate_sandboxes

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
