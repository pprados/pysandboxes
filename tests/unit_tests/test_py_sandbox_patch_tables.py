# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Key-disjointness of the six patch tables merged in py_sandbox.py.

``activate_sandboxes`` merges ``env_patch_rules``, ``file_patch_rules``,
``socket_patch_rules``, ``import_patch_rules``, ``self_patch_rules`` and
``api_patch_rules`` flat, with ``api_patch_rules`` last. A key collision
between two tables would not double-wrap (visible) but silently
overwrite one guard's factory with another's (invisible) — this pins
down that no such collision exists, beyond the one known exception.
"""

import itertools

from pysandboxes import (
    guard_api,
    guard_envs,
    guard_files,
    guard_import,
    guard_self,
    guard_socket,
)

# Known collision, introduced by this branch's guard_api registry, not
# fixed here: guard_files already patched "os.chroot" for its path
# argument; guard_api now patches it again as a "privileges" sensitive
# call, and the flat merge in py_sandbox.py keeps only the second,
# silently dropping the first. Remediation (drop one side, or compose
# both factories) changes the sandbox's security posture and is left
# to the owner. Keyed by the exact pair, not the bare name, so a third
# table patching "os.chroot" would still be caught.
_KNOWN_COLLISIONS: dict[tuple[str, str], frozenset[str]] = {
    ("guard_files", "guard_api"): frozenset({"os.chroot"}),
}


def test_patch_table_keys_are_pairwise_disjoint() -> None:
    """No two of the six patch tables share a key, but the known one."""
    tables = {
        "guard_envs": guard_envs.patch_rules(learn=False),
        "guard_files": guard_files.patch_rules(learn=False),
        "guard_socket": guard_socket.patch_rules(learn=False),
        "guard_import": guard_import.patch_rules(learn=False),
        "guard_self": guard_self.patch_rules(learn=False),
        "guard_api": guard_api.patch_rules(learn=False),
    }
    pairs = itertools.combinations(tables.items(), 2)
    for (name_a, table_a), (name_b, table_b) in pairs:
        allowed = _KNOWN_COLLISIONS.get((name_a, name_b), frozenset())
        shared = (set(table_a) & set(table_b)) - allowed
        assert not shared, f"{name_a} and {name_b} both patch {shared}"
