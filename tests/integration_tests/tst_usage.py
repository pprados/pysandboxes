import asyncio
import importlib
import os
import sys
from pprint import pprint

from pysandboxes import guard_files
from pysandboxes.guard_import import _activate_patch_import, PatchRules
from pysandboxes.immutable_dict import ImmutableDict


if __name__ == "__main__":

    from tests.integration_tests.sb_usage import main
    # main()
    asyncio.run(main(sys.argv))
