# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Remove a relative directory tree and walk another one inside a sandbox, and print ``TREE_REMOVED``.

Both calls resolve a relative name through a directory descriptor (``dir_fd``). Run as a module:
``python -m tests.integration_tests.tst_rmtree_without_proc``.
"""

import os
import shutil

from pysandboxes import sandbox, sandboxes


@sandbox
def _remove_and_walk() -> str:
    os.makedirs("tmp/rmtree_without_proc/a/b", exist_ok=True)
    with open("tmp/rmtree_without_proc/a/b/f.txt", "w", encoding="utf-8") as f:
        f.write("x")
    walked = [name for _, _, files, _ in os.fwalk("tmp/rmtree_without_proc") for name in files]
    shutil.rmtree("tmp/rmtree_without_proc")
    return f"{walked} {os.path.exists('tmp/rmtree_without_proc')}"


def main() -> None:
    with sandboxes(sandboxes_config="tests/integration_tests/py-sandbox-test.profile"):
        print("TREE_REMOVED", _remove_and_walk(), flush=True)


if __name__ == "__main__":
    main()
