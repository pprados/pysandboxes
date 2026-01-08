import base64
import contextvars
from typing import Any, Optional
import pickle

_is_in_sandbox=False

_sandboxed=contextvars.ContextVar(
    'sanboxed', default=False)

def is_in_sandbox():
    return _sandboxed.get()

def set_is_in_sandbox(value: bool):
    _sandboxed.set(value)

def _to_b85(obj: Any) -> str:
    return base64.b85encode(
        pickle.dumps(obj,
                     protocol=pickle.HIGHEST_PROTOCOL
                     )).decode("utf-8")


def _from_b85(b85: str) -> Any:
    return pickle.loads(
        base64.b85decode(b85.encode("utf-8")),
    )
