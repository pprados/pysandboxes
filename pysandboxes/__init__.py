from importlib import metadata
from .remote.sandboxes import sandbox,run
from .guard_sandbox import activate_sandboxes

try:
    __version__ = metadata.version(__package__)
except metadata.PackageNotFoundError:
    # Case where package metadata is not available.
    __version__ = ""

__all__=[
    "sandbox",
    "run",
    "activate_sandboxes",
]