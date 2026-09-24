# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Session teardown shared by the integration and the container suites.

``tst_usage`` writes these files by design and cannot remove them itself: it is
the script being sandboxed, so a denial aborts it before any cleanup it would
carry, and ``denied-write.probe`` only exists at all when a guard failed to deny
it. Removing them belongs to the harness, which runs outside the sandbox.
"""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest  # type: ignore[import-untyped]

# Both suites run tst_usage from the project root (parent of tests/).
_ROOT_DIR = Path(__file__).resolve().parent.parent

# Modules testing a Linux-only provider. They are left out of the collection, not skipped:
# a skip happens after the import, and these modules import what other platforms lack.
# A provider suite that must run everywhere goes through `provider_skip_reason` instead.
_LINUX_ONLY_TESTS = [
    "containers_tests/*",
    "integration_tests/test_slirp_cleanup.py",
    "integration_tests/remote/test_bwrap.py",
    "integration_tests/remote/test_firejail.py",
    "integration_tests/remote/test_landlock.py",
    "integration_tests/remote/test_unshare.py",
    "unit_tests/test_qemu_*.py",
    "unit_tests/remote/test_bwrap_*.py",
    "unit_tests/remote/test_landlock_*.py",
    "unit_tests/remote/test_qemu_*.py",
]
collect_ignore_glob = [] if sys.platform == "linux" else _LINUX_ONLY_TESTS

_RESIDUES = ("tmp/test.remove", "denied-write.probe")


@pytest.fixture(scope="session", autouse=True)
def _remove_test_residues() -> Iterator[None]:
    """Leave no probe file behind, whatever the run did."""
    yield
    for name in _RESIDUES:
        try:
            (_ROOT_DIR / name).unlink(missing_ok=True)
        except OSError:
            # Under qemu the file comes back owned by a mapped uid (nobody), so
            # the unlink can be refused; a residue is not worth failing on.
            pass
