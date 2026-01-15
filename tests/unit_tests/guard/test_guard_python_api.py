import sys
from typing import List

import pytest

from pysandboxes.guard_python_api import parse_rules, activate_guard_python_api, \
    _loaded_sys_modules
from pysandboxes.remote import ConfigLines


@pytest.fixture(autouse=True)
def reset_rules():
    from pysandboxes.guard_python_api import _deactivate_guard_python_api

    yield
    # _deactivate_guard_python_api()


def str_activate_guard_python_api(rules: ConfigLines) -> None:
    python_api_rules, _ = parse_rules(rules)
    activate_guard_python_api(python_api_rules)


# _default_python_rules = f"--python-api-import=ALLOW:{','.join(_loaded_sys_modules())}"
_default_python_rules = (f"--python-api-import=ALLOW:"
                        "abc,_abc,"
                         "builtins,"
                         "collections,_collections,_collections_abc,"
                         "copyreg,"
                         "dataclasses,"
                         "functools,_functools,"
                         "itertools,keyword,enum,_collections,"
                         "operator,_operator,"
                         "reprlib,"
                         "types,"
                         "io,_io,"
                         '_thread,'
                         "_weakref,"
                         "sys,")


def test_guard_python_api_import():
    rules = [
        _default_python_rules,
        "--python-api-import=ALLOW:_pytest.*,faulthandler,teamcity",
        "--python-api-import=ALLOW:re.*",
        # "--python-api-import=LEARN",
    ]

    str_activate_guard_python_api(rules)
    import re
    re.escape("test")  # Accepted ?
