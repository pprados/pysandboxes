import logging
from importlib import metadata

# from .sandboxes import sandbox, run, sandboxes
# from .sandboxes import sandbox

try:
    __version__ = metadata.version(__package__)
except metadata.PackageNotFoundError:
    # Case where package metadata is not available.
    __version__ = ""

# FIXME: circular import
# __all__ = [
#     "sandbox",
#     "run",
#     "sandboxes",
#     "SandBoxError",
# ]
