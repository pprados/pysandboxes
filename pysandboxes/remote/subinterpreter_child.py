# Copyright (c) 2026, Philippe Prados (pprados)
# License: Apache V2
"""The half of the ``subinterpreter`` provider that runs inside the subinterpreter.

Imported there before the guards are armed, like ``main_sandbox`` in a child
process: everything the calls need afterwards is bound here, since arming
evicts ``sys.modules`` and charges every later import to the user's rules.
Replies go back as frames on a pipe, because the interpreter has no return
channel common to Python 3.12, 3.13 and 3.14.
"""

import asyncio
import base64
import importlib
import inspect
import json
import logging
import os
import pickle
import struct
import sys
import traceback
from typing import Any

import tblib

from ..all_rules import AllRules
from ..e import sandbox_denials
from ..guard_import import framework_imports, preimport_framework_module, user_code
from ..learning import add_learning_rule, is_learning_mode, set_learning_mode, set_learning_path
from ..lifecycle import arm
from ..tools import set_is_in_sandbox
from .tools import describe_exception, from_b85, result_requires_objects, to_b85

_write = os.write
# Bound before arming: guard_api patches pickle.loads in this interpreter, and these payloads come from the host.
_pickle_loads = pickle.loads
_loop: asyncio.AbstractEventLoop | None = None


def write_frame(fd: int, data: bytes) -> None:
    """Write one length-prefixed frame to ``fd``."""
    view = memoryview(struct.pack("!Q", len(data)) + data)
    while view:
        view = view[_write(fd, view) :]


def _narrow_environ(envs: dict[str, str]) -> None:
    """Keep only the profile's variables in this interpreter's view of the environment.

    ``os.environ`` is rebuilt from the process environment for each interpreter. Clearing
    it the usual way calls ``unsetenv()`` on the environment the host shares, so the
    mappings are emptied directly instead: the C-level environment is left untouched.
    """
    os.environ._data.clear()  # type: ignore[attr-defined]
    for key, value in envs.items():
        os.environ._data[os.environ.encodekey(key)] = os.environ.encodevalue(value)  # type: ignore[attr-defined]
    posix = sys.modules.get("posix") or sys.modules.get("nt")
    if posix is not None:
        posix.environ.clear()
        posix.environ.update({os.fsencode(key): os.fsencode(value) for key, value in envs.items()})


def _activate(rules_payload: bytes, log_level: int) -> AllRules:
    """Arm the Python layer in this interpreter, as ``main_sandbox.main()`` does in a child."""
    from ..guard_socket import apply_pin_dns_resolution, set_pin_dns
    from ..py_sandbox import activate_sandboxes

    logging.basicConfig(level=log_level)
    all_rules: AllRules = _pickle_loads(rules_payload)  # Payload built by the host, in this very process
    if not all_rules.learn:
        _narrow_environ({key: str(value) if value is not None else "" for key, value in all_rules.envs.items()})
    set_learning_path(all_rules.learning_path)
    set_pin_dns(all_rules.pin_dns)
    if all_rules.pin_dns:
        import socket

        apply_pin_dns_resolution(socket)
    preimport_framework_module("tblib")
    activate_sandboxes(all_rules, os.environ, rules_provider="none")
    set_is_in_sandbox(True)
    set_learning_mode(all_rules.learn)
    return all_rules


def boot(rules_payload: bytes, log_level: int, init_fn: str) -> None:
    """Arm the guards, run ``init_fn``, and get ready for the calls."""
    global _loop
    _activate(rules_payload, log_level)
    with framework_imports():
        _loop = asyncio.new_event_loop()
    if init_fn:
        module_name, function_name = init_fn.split(":", 1)
        with user_code():
            function = getattr(importlib.import_module(module_name), function_name)
            if inspect.iscoroutinefunction(function):
                _loop.run_until_complete(function())
            else:
                function()
    arm()


def _invoke(payload: bytes) -> dict[str, Any]:
    """Run one call and build the reply the SSE daemon would send."""
    assert _loop is not None, "boot() was not called"
    function_id, args_b85, kwargs_b85 = _pickle_loads(payload)  # Payload built by the host
    module_name, function_name = function_id.split(":", 1)
    try:
        with user_code():
            module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        args, kwargs = from_b85(args_b85), from_b85(kwargs_b85)
        if inspect.iscoroutinefunction(function):
            result = _loop.run_until_complete(function(*args, **kwargs))
        else:
            result = function(*args, **kwargs)
    except Exception as exception:  # noqa: BLE001  # every user exception goes back to the caller
        serial_traceback = tblib.Traceback(exception.__traceback__)
        reply: dict[str, Any] = {
            "exception_fallback": base64.b85encode(
                pickle.dumps(
                    (describe_exception(exception, sandbox_denials(exception)), serial_traceback),
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            ).decode("utf-8")
        }
        try:
            reply["exception"] = base64.b85encode(
                pickle.dumps((exception, serial_traceback), protocol=pickle.HIGHEST_PROTOCOL)
            ).decode("utf-8")
        except Exception:  # noqa: BLE001  # the descriptor still carries the refusal
            reply["exception"] = ""
        return reply
    encoded = to_b85(result)
    if is_learning_mode():
        add_learning_rule(f"remote-result-mode={'objects' if result_requires_objects(encoded) else 'data-only'}")
    return {"result": encoded}


def call(fd: int, payload: bytes) -> None:
    """Run one call; the reply always goes back, even when it cannot be built."""
    try:
        reply = _invoke(payload)
    except BaseException as error:  # noqa: BLE001  # SystemExit included: the host must not wait forever
        reply = {"error": repr(error)}
    write_frame(fd, json.dumps(reply).encode("utf-8"))


def python_sb(fd: int, rules_payload: bytes, log_level: int, python_cmd: list[str]) -> None:
    """Run a whole program, as ``python-sb`` does in a child process, and send back its exit code."""
    import pysandboxes.remote.python_in_sb as python_in_sb_module  # loaded before arming

    rc: int = 1
    try:
        all_rules = _activate(rules_payload, log_level)
        rc = python_in_sb_module.python_in_sb(all_rules, python_cmd)
    except SystemExit as exit_request:
        code = exit_request.code
        rc = code if isinstance(code, int) else (0 if code is None else 1)
        if code is not None and not isinstance(code, int):
            print(code, file=sys.stderr)
    except BaseException:  # noqa: BLE001  # reported, then turned into an exit code
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        write_frame(fd, json.dumps({"rc": rc}).encode("utf-8"))
