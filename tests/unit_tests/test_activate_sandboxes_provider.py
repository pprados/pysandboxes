# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`activate_sandboxes` hands the rules to the OS provider before the Python guards are armed."""

from pathlib import Path
from typing import Any

import pytest

from pysandboxes import _os_sandbox, py_sandbox
from pysandboxes.py_sandbox import activate_sandboxes, load_and_parse_config


class _RecordingProvider:
    def __init__(self, key: str, calls: list[str]) -> None:
        self._key = key
        self._calls = calls

    def update_rules_and_activate(self, **kwargs: Any) -> Any:
        self._calls.append(self._key)
        return kwargs["all_rules"]


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch, rules: Any) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        _os_sandbox,
        "providers_factory",
        {key: lambda token, _key=key: _RecordingProvider(_key, calls) for key in ("subprocess", "none")},
    )
    return calls


@pytest.fixture
def rules(tmp_path: Path) -> Any:
    profile = tmp_path / "test.profile"
    profile.write_text("os-sandbox=subprocess\npy-sandbox=false\n")
    return load_and_parse_config(profile)


def test_rules_provider_overrides_the_configured_provider(providers: list[str], rules: Any) -> None:
    activate_sandboxes(rules, rules_provider="none")

    assert providers == ["none"]


def test_the_provider_is_handed_the_rules_and_the_environment_and_no_directory(
    monkeypatch: pytest.MonkeyPatch, rules: Any
) -> None:
    received: list[set[str]] = []

    class _Provider:
        def update_rules_and_activate(self, **kwargs: Any) -> Any:
            received.append(set(kwargs))
            return kwargs["all_rules"]

    monkeypatch.setattr(_os_sandbox, "providers_factory", {"subprocess": lambda token: _Provider()})

    activate_sandboxes(rules)

    assert received == [{"all_rules", "envs"}]


def test_a_process_confined_before_it_started_does_not_call_its_provider(providers: list[str], rules: Any) -> None:
    activate_sandboxes(rules, run_provider=False)

    assert providers == []


def test_a_process_confined_before_it_started_still_loads_its_provider_module(
    monkeypatch: pytest.MonkeyPatch, rules: Any
) -> None:
    looked_up: list[str] = []

    class _Factory(dict[str, Any]):
        def __getitem__(self, key: str) -> Any:
            looked_up.append(key)
            return super().__getitem__(key)

    monkeypatch.setattr(_os_sandbox, "providers_factory", _Factory(subprocess=lambda token: None))

    activate_sandboxes(rules, run_provider=False)

    assert looked_up == ["subprocess"]


def test_the_temporary_directory_is_found_before_the_guards_are_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "armed.profile"
    profile.write_text("os-sandbox=subprocess\n")
    journal: list[str] = []

    class _Stop(Exception):
        pass

    def arm(learn: bool) -> Any:
        journal.append("arm")
        raise _Stop

    def find_tempdir() -> str:
        journal.append("tempdir")
        return ""

    monkeypatch.setattr(py_sandbox.tempfile, "gettempdir", find_tempdir)
    monkeypatch.setattr(py_sandbox.guard_envs, "patch_rules", arm)

    with pytest.raises(_Stop):
        activate_sandboxes(load_and_parse_config(profile))

    assert journal == ["tempdir", "arm"]


def test_an_unknown_provider_is_refused(providers: list[str], rules: Any) -> None:
    with pytest.raises(ValueError, match="Unknown os-sandbox name: nope"):
        activate_sandboxes(rules, rules_provider="nope")
