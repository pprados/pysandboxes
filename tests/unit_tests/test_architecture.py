# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The import layering of the package: a guard never reaches a provider, a provider never reaches a peer.

The imports made inside a function count too: that is how the lower layers reach the upper ones.
"""

from pathlib import Path

import pytest
from pytestarch import EvaluableArchitecture, Rule, get_evaluable_architecture

PACKAGE = Path(__file__).parents[2] / "pysandboxes"

GUARDS = ("guard_wraps", "guard_envs", "guard_api", "guard_import", "guard_files", "guard_socket", "guard_eval")
ENTRY_POINTS = ("python_sb", "sandboxes_api")
PROVIDERS = (
    "remote.bwrap_sse_daemon",
    "remote.firejail_sse_daemon",
    "remote.landlock_daemon",
    "remote.none_daemon",
    "remote.qemu_sse_daemon",
    "remote.unshare_sse_daemon",
)
# What each guard may build on. A guard imports nothing above its layer.
GUARD_FOUNDATIONS = {
    "guard_wraps": (),
    "guard_envs": ("guard_wraps",),
    "guard_api": ("guard_wraps",),
    "guard_import": ("guard_wraps",),
    "guard_files": ("guard_wraps", "guard_envs"),
    "guard_socket": ("guard_wraps", "guard_files"),
    "guard_eval": ("guard_wraps", "guard_api", "guard_files"),
}


@pytest.fixture(scope="module")
def architecture() -> EvaluableArchitecture:
    return get_evaluable_architecture(str(PACKAGE), str(PACKAGE))


def _never_imports(architecture: EvaluableArchitecture, importer: str, imported: str) -> None:
    rule = (
        Rule()
        .modules_that()
        .are_named(f"pysandboxes.{importer}")
        .should_not()
        .import_modules_that()
        .are_named(f"pysandboxes.{imported}")
    )
    rule.assert_applies(architecture)


@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize("above", ENTRY_POINTS + ("remote",))
def test_a_guard_never_reaches_the_entry_points_or_the_providers(
    architecture: EvaluableArchitecture, guard: str, above: str
) -> None:
    _never_imports(architecture, guard, above)


@pytest.mark.parametrize(
    ("guard", "above"),
    [
        (guard, other)
        for guard in GUARDS
        for other in GUARDS
        if other != guard and other not in GUARD_FOUNDATIONS[guard]
    ],
)
def test_a_guard_builds_only_on_the_guards_below_it(
    architecture: EvaluableArchitecture, guard: str, above: str
) -> None:
    _never_imports(architecture, guard, above)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("above", ENTRY_POINTS)
def test_a_provider_never_reaches_the_entry_points(
    architecture: EvaluableArchitecture, provider: str, above: str
) -> None:
    _never_imports(architecture, provider, above)


@pytest.mark.parametrize(
    ("provider", "peer"), [(a, b) for a in PROVIDERS for b in PROVIDERS if a != b], ids=lambda name: name[7:]
)
def test_a_provider_never_imports_another_provider(
    architecture: EvaluableArchitecture, provider: str, peer: str
) -> None:
    _never_imports(architecture, provider, peer)


def test_only_the_registry_and_the_cli_reach_the_remote_package(architecture: EvaluableArchitecture) -> None:
    rule = (
        Rule()
        .modules_that()
        .have_name_matching(r"pysandboxes\.(?!remote|_os_sandbox$|python_sb$).+")
        .should_not()
        .import_modules_that()
        .are_sub_modules_of("pysandboxes.remote")
    )
    rule.assert_applies(architecture)
