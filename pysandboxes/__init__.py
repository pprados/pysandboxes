from importlib import metadata
from .remote.sandbox import sandbox
from .sandbox import activate_sandboxes

try:
    __version__ = metadata.version(__package__)
except metadata.PackageNotFoundError:
    # Case where package metadata is not available.
    __version__ = ""

__all__=[
    "sandbox",
    "activate_sandboxes",
]