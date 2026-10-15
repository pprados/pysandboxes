# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""``os-sandbox=subinterpreter``: the Python guards armed in a subinterpreter of the host process.

The calls run in an isolated subinterpreter (own GIL, own ``sys.modules`` and
builtins, no fork): the guards are patched there, never in the host, and no
process is started. It is not an OS boundary: the subinterpreter shares the
host's memory, file descriptors, working directory, C-level environment and
privileges. Compiled code, or anything that walks around the Python guards,
reaches the host itself. See ``wiki/subinterpreter.md``.
"""

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import pickle
import select
import struct
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from ..all_rules import AllRules
from ..base_daemon import BaseDaemon
from ..e import SandBoxProtocolError
from ..sb_types import Envs
from ..tools import Environ, SyncOrAsyncFunc, get_callable_info, is_in_sandbox
from .base_sse_daemon import _rebuild_remote_exception
from .parameters import TIMEOUT_FOR_RPC_CALL, TIMEOUT_FOR_START_DAEMON
from .subinterpreter_child import write_frame
from .tools import from_b85_restricted, result_predicate, to_b85

logger = logging.getLogger(__name__)

# The module behind PEP 554/734 from 3.13 (`_xxsubinterpreters` before, not usable here).
_API_MODULE = "_interpreters"

# Run first in the new interpreter: the host's import path, then the half that arms the guards there.
_PRELUDE = (
    "import json, sys\n"
    "sys.path[:] = json.loads(_pysb_path)\n"
    "from pysandboxes.remote import subinterpreter_child as _pysb_child\n"
)


def _api_module_name() -> str | None:
    """Return the name of the low-level subinterpreter module, or None when this Python has none."""
    return _API_MODULE if importlib.util.find_spec(_API_MODULE) is not None else None


def _api() -> ModuleType:
    return importlib.import_module(_API_MODULE)


def _create_isolated() -> Any:
    return _api().create("isolated")


def _read_exactly(fd: int, size: int, deadline: float | None) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        if deadline is not None and not select.select([fd], [], [], max(0.0, deadline - time.monotonic()))[0]:
            raise SandBoxProtocolError("The subinterpreter did not reply in time.")
        chunk = os.read(fd, size - len(chunks))
        if not chunk:
            raise SandBoxProtocolError("The subinterpreter closed its reply channel.")
        chunks += chunk
    return bytes(chunks)


def _read_frame(fd: int, deadline: float | None) -> bytes:
    (size,) = struct.unpack("!Q", _read_exactly(fd, 8, deadline))
    return _read_exactly(fd, size, deadline)


class SubInterpreterDaemon(BaseDaemon):
    """Run the sandboxed calls in an isolated subinterpreter of the current process."""

    __slots__ = ("_interp_id", "_lock", "_result_guard", "_result_data_only")

    def __init__(self, token: str, **kwargs: Any) -> None:
        super().__init__(token)
        self._interp_id: Any = None
        self._lock = threading.Lock()
        self._result_guard = True
        self._result_data_only = True

    @classmethod
    def unavailable_reason(cls) -> str | None:
        # 3.11 and 3.12 ship _xxsubinterpreters too, but not usable here. On 3.11 every
        # interpreter shares one GIL and asyncio's C state. On 3.12 an isolated interpreter
        # cannot load zoneinfo (no datetime C API), and once a run failed, destroy() hangs.
        if sys.version_info < (3, 13) or _api_module_name() is None:
            return f"os-sandbox 'subinterpreter' needs Python 3.13 or later, this is {sys.version.split()[0]}"
        return None

    def update_rules_and_activate(
        self,
        *,
        envs: Envs,
        all_rules: AllRules,
        temp: Path,
    ) -> AllRules:
        return all_rules

    def _run(self, code: str, shared: dict[str, Any], timeout: float | None) -> bytes:
        """Run ``code`` in the subinterpreter and return the frame it writes on ``_pysb_fd``.

        The interpreter runs in a worker thread while this one reads, so a reply larger
        than the pipe buffer cannot block. The worker appends an empty frame once the code
        returns: when it comes first, the code ended without replying. A subinterpreter
        cannot be killed: on timeout, the call is left running and the interpreter stays busy.
        """
        api = _api()
        failure: list[str] = []
        with self._lock:
            read_fd, write_fd = os.pipe()

            def _worker() -> None:
                try:
                    excinfo = api.run_string(self._interp_id, code, {**shared, "_pysb_fd": write_fd})
                    if excinfo is not None:  # the uncaught exception, as a snapshot
                        failure.append(f"{excinfo.type.__name__}: {excinfo.msg}")
                except Exception as error:  # noqa: BLE001  # reported to the caller below
                    failure.append(repr(error))
                finally:
                    try:
                        write_frame(write_fd, b"")
                    except OSError:  # the reader gave up on a timeout and closed its end
                        pass
                    os.close(write_fd)

            worker = threading.Thread(target=_worker, name="subinterpreter-call", daemon=True)
            worker.start()
            deadline = None if timeout is None else time.monotonic() + timeout
            try:
                reply = _read_frame(read_fd, deadline)
                if reply:
                    _read_frame(read_fd, deadline)  # the worker's end marker
                worker.join()
            finally:
                os.close(read_fd)
        if not reply:
            raise SandBoxProtocolError(f"The subinterpreter did not reply: {failure[0] if failure else 'no detail'}")
        return reply

    async def _start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        if reason := self.unavailable_reason():
            raise RuntimeError(reason)
        if not all_rules.use_py_sandbox:
            logger.warning(
                "os-sandbox=subinterpreter with py-sandbox=false enforces nothing: "
                "no expose-ro/expose-rw/ignore/net/env rule holds without the Python guards"
            )
        else:
            logger.warning(
                "os-sandbox=subinterpreter is no OS boundary: the expose-ro/expose-rw/ignore/net/env rules "
                "are held by the Python guards only, inside the host process"
            )
        self._result_guard = all_rules.remote_result_guard
        self._result_data_only = all_rules.remote_result_data_only
        if init_fn:
            module, name = get_callable_info(init_fn)
            init_fn_ref = f"{module}:{name}"
        else:
            init_fn_ref = ""
        self._interp_id = _create_isolated()
        code = _PRELUDE + (
            "_pysb_child.boot(_pysb_rules, _pysb_log_level, _pysb_init_fn)\n"
            "_pysb_child.write_frame(_pysb_fd, b'ok')\n"
        )
        shared = {
            "_pysb_path": json.dumps(sys.path),
            "_pysb_rules": pickle.dumps(all_rules),
            "_pysb_log_level": log_level,
            "_pysb_init_fn": init_fn_ref,
        }
        try:
            await asyncio.to_thread(self._run, code, shared, TIMEOUT_FOR_START_DAEMON)
        except BaseException:
            self._destroy()
            raise
        self._is_started = True
        self._accept_incoming = True

    def _destroy(self) -> None:
        if self._interp_id is None:
            return
        try:
            _api().destroy(self._interp_id)
        except Exception as error:  # noqa: BLE001  # a running interpreter cannot be destroyed
            logger.warning("The subinterpreter could not be destroyed: %r", error)
        self._interp_id = None

    async def _stop(self, max_pending: int) -> None:
        self._accept_incoming = False

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        self._accept_incoming = False
        if self._lock.acquire(timeout=TIMEOUT_FOR_RPC_CALL if graceful_shutdown else 0):
            try:
                self._destroy()
            finally:
                self._lock.release()
        else:
            logger.warning("A call is still running in the subinterpreter: it is left behind, not destroyed")
        self._is_started = False

    def _call(self, func: Callable[..., Any], args: Any, kwargs: Any) -> Any:
        module_name, callable_name = get_callable_info(func)
        payload = pickle.dumps((f"{module_name}:{callable_name}", to_b85(args), to_b85(kwargs)))
        reply = json.loads(
            self._run("_pysb_child.call(_pysb_fd, _pysb_payload)\n", {"_pysb_payload": payload}, TIMEOUT_FOR_RPC_CALL)
        )
        if "result" in reply:
            return from_b85_restricted(
                reply["result"],
                result_predicate if self._result_guard else None,
                data_only=self._result_data_only,
            )
        if "exception" in reply:
            raise _rebuild_remote_exception(reply["exception"], reply.get("exception_fallback"))
        raise SandBoxProtocolError(f"Sandbox reported: {reply.get('error', 'an unknown reply')}")

    def _check_incoming(self, _force_incomming: bool) -> None:
        if not _force_incomming and not self._accept_incoming:
            raise SandBoxProtocolError("The sandbox daemon is being stopped.")

    async def async_call_in_sandbox(
        self,
        func: Callable[..., Any],
        _force_incomming: bool,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if is_in_sandbox():
            return await func(*args, **kwargs)
        self._check_incoming(_force_incomming)
        return await asyncio.to_thread(self._call, func, args, kwargs)

    def call_in_sandbox(
        self,
        func: Callable[..., Any],
        _force_incomming: bool,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if is_in_sandbox():
            return func(*args, **kwargs)
        self._check_incoming(_force_incomming)
        return self._call(func, args, kwargs)

    def run_python_sb(self, all_rules: AllRules, python_cmd: list[str], log_level: int) -> int:
        """Run a whole program in the subinterpreter, for ``python-sb``, and return its exit code."""
        self._interp_id = _create_isolated()
        code = _PRELUDE + "_pysb_child.python_sb(_pysb_fd, _pysb_rules, _pysb_log_level, json.loads(_pysb_cmd))\n"
        shared = {
            "_pysb_path": json.dumps(sys.path),
            "_pysb_rules": pickle.dumps(all_rules),
            "_pysb_log_level": log_level,
            "_pysb_cmd": json.dumps(python_cmd),
        }
        try:
            reply = self._run(code, shared, timeout=None)
        finally:
            self._destroy()
        rc = json.loads(reply).get("rc", 1)
        return rc if isinstance(rc, int) else 1
