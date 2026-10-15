# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The same calls through each kernel-backed provider, started the way its users start it."""

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncGenerator, Callable, NamedTuple

import pytest  # type: ignore[import-untyped]
import pytest_asyncio  # type: ignore[import-untyped]

from pysandboxes import sandbox
from pysandboxes._os_sandbox import async_shutdown_daemon, async_start_daemon, shutdown_daemon, start_daemon
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.landlock_daemon import landlock_user_available
from pysandboxes.remote.tools import unshare_user_namespace_available

from .._env import NO_DEFAULT_ROUTE_REASON, default_route_available, provider_skip_reason


class _Provider(NamedTuple):
    name: str
    skip_reason: Callable[[], str | None]
    asynchronous: bool


def _with_default_route(name: str) -> str | None:
    # The provider derives its network namespace from the host default interface.
    return provider_skip_reason(name) or (None if default_route_available() else NO_DEFAULT_ROUTE_REASON)


def _unshare_skip_reason() -> str | None:
    # slirp4netns installs a default route in the namespace, copied from the host one.
    if unshare_user_namespace_available() and default_route_available():
        return None
    return (
        "unshare/slirp4netns missing, user namespaces not permitted (e.g. in containers), "
        f"or: {NO_DEFAULT_ROUTE_REASON}"
    )


def _landlock_skip_reason() -> str | None:
    return None if landlock_user_available() else "Landlock not available (kernel < 5.13 or not Linux)"


# bwrap and firejail start through the async API, unshare and landlock through the sync one.
_PROVIDERS = (
    _Provider("bwrap", lambda: provider_skip_reason("bwrap"), True),
    _Provider("firejail", lambda: _with_default_route("firejail"), True),
    _Provider("landlock", _landlock_skip_reason, False),
    _Provider("unshare", _unshare_skip_reason, False),
)


@pytest_asyncio.fixture(scope="module", params=_PROVIDERS, ids=lambda provider: provider.name, autouse=True)
async def provider(request: pytest.FixtureRequest) -> AsyncGenerator[_Provider, None]:
    chosen: _Provider = request.param
    if reason := chosen.skip_reason():
        pytest.skip(reason)
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    all_rules = load_and_parse_config(config_path=config_path)
    all_rules = all_rules._replace(os_sandbox=chosen.name)
    if chosen.name == "bwrap":
        all_rules = all_rules._replace(os_sandbox_params=ImmutableDict({}))
    start = dict(envs=os.environ, log_level=logging.root.getEffectiveLevel(), init_fn=None)
    if chosen.asynchronous:
        await async_start_daemon(all_rules, **start)  # type: ignore[arg-type]
        yield chosen
        await async_shutdown_daemon(graceful_shutdown=False)
    else:
        await asyncio.to_thread(start_daemon, all_rules, **start)  # type: ignore[arg-type]
        yield chosen
        await asyncio.to_thread(shutdown_daemon, graceful_shutdown=False)


@sandbox()
def sync_function(a: str, b: str) -> str:
    return f"{a} {b}"


def test_sync_function() -> None:
    assert sync_function("a", b="b") == "a b"


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio

    await asyncio.sleep(0)
    return f"{a} {b}"


async def test_async_function() -> None:
    assert await async_function("a", b="b") == "a b"
