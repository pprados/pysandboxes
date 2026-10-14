# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`activate_sandboxes` hands the rules to the OS provider before the Python guards are armed."""

from pathlib import Path
from typing import Any

import pytest

from pysandboxes import _os_sandbox
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


def test_the_configured_provider_updates_the_rules(providers: list[str], rules: Any) -> None:
    activate_sandboxes(rules)

    assert providers == ["subprocess"]


def test_rules_provider_overrides_the_configured_provider(providers: list[str], rules: Any) -> None:
    activate_sandboxes(rules, rules_provider="none")

    assert providers == ["none"]


def test_an_unknown_provider_is_refused(providers: list[str], rules: Any) -> None:
    with pytest.raises(ValueError, match="Unknown os-sandbox name: nope"):
        activate_sandboxes(rules, rules_provider="nope")
