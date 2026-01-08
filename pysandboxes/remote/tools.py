import base64
from typing import Any, Optional
import pickle

_is_in_sandbox=False

def is_in_sandbox():
    return _is_in_sandbox

def set_is_in_sandbox(value: bool):
    global _is_in_sandbox
    _is_in_sandbox = value

def _to_b85(obj: Any) -> str:
    return base64.b85encode(
        pickle.dumps(obj,
                     protocol=pickle.HIGHEST_PROTOCOL
                     )).decode("utf-8")


def _from_b85(b85: str) -> Any:
    return pickle.loads(
        base64.b85decode(b85.encode("utf-8")),
    )
