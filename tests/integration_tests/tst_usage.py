import importlib
import os
from pprint import pprint

from pysandboxes import guard_files
from pysandboxes.guard_import import _activate_patch_import, PatchRules
from pysandboxes.immutable_dict import ImmutableDict


if __name__ == "__main__":

    # patch_rules: PatchRules = guard_files.patch_rules()  # TODO: dans socket egalement
    # _activate_patch_import(patch_rules)
    #
    # import sys
    # z=sys.modules
    # 'tests.integration_tests.sb_usage' in sys.modules
    # import sys
    # print(list(sys.modules.keys()))
    from tests.integration_tests.sb_usage import main
    main()
