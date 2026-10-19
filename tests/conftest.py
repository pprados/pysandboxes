# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Session teardown shared by the integration and the container suites.

``tst_usage`` writes these files by design and cannot remove them itself: it is
the script being sandboxed, so a denial aborts it before any cleanup it would
carry, and ``denied-write.probe`` only exists at all when a guard failed to deny
it. Removing them belongs to the harness, which runs outside the sandbox.
"""

import os
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
    "integration_tests/remote/test_providers.py",
    "unit_tests/test_qemu_*.py",
    "unit_tests/remote/test_bwrap_*.py",
    "unit_tests/remote/test_*landlock*.py",
    "unit_tests/remote/test_qemu_*.py",
    "unit_tests/remote/test_*unshare*.py",
    "unit_tests/remote/test_*firejail*.py",
    "unit_tests/remote/test_apply_netfilter.py",
    "unit_tests/fault_injection/test_landlock_*.py",
]

# Modules that run the release scripts (bash, git) the maintainer and the CI use, and the import layering check,
# whose parser reads the sources with the platform encoding. None of them depends on what Windows runs.
_NOT_ON_WINDOWS_TESTS = [
    "unit_tests/test_architecture.py",
    "unit_tests/test_changelog_draft.py",
    "unit_tests/test_checked_commits.py",
    "unit_tests/test_image_tags.py",
    "unit_tests/test_nightly_gate_reuse.py",
    "unit_tests/test_python_patch.py",
    "unit_tests/test_python_sb_release.py",
    "unit_tests/test_refresh_images.py",
    "unit_tests/test_release_tag.py",
    "unit_tests/test_smoke_test_images.py",
    "unit_tests/test_tag_release.py",
    "unit_tests/test_verify_published.py",
]
collect_ignore_glob = [] if sys.platform == "linux" else _LINUX_ONLY_TESTS
if sys.platform == "win32":
    collect_ignore_glob = [*collect_ignore_glob, *_NOT_ON_WINDOWS_TESTS]

# A script that calls an LLM (scripts/changelog-draft.sh) gets a command that fails, so no test spends tokens by
# omission. Only the tests marked `llm` call the model, and only with RUN_LLM_TESTS=1.
os.environ.setdefault("CHANGELOG_LLM", "false")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("RUN_LLM_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="calls an LLM and spends tokens: set RUN_LLM_TESTS=1 to run it")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


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
