import logging
from importlib import metadata

from .exception import SandBoxError
from .sandboxes import sandboxes,sandbox,run

try:
    __version__ = metadata.version(__package__)
except metadata.PackageNotFoundError:
    # Case where package metadata is not available.
    __version__ = ""

__all__ = [
    "sandbox",
    "run",
    "sandboxes",
    "SandBoxError",
]
