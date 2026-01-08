from importlib import metadata
from .remote.sandbox import sandbox

try:
    __version__ = metadata.version(__package__)
except metadata.PackageNotFoundError:
    # Case where package metadata is not available.
    __version__ = ""

__all__=["sandbox"]