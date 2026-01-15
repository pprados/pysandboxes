from importlib import metadata
from .remote.sandboxes import sandbox
from .remote.sandboxes import sandbox,run,sandboxes
from .guard_sandbox import activate_sandboxes

try:
    __version__ = metadata.version(__package__)
except metadata.PackageNotFoundError:
    # Case where package metadata is not available.
    __version__ = ""

__all__=[
    "sandbox",
    "run",
    "sandboxes",
    "activate_sandboxes",
]