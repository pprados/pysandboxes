# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The system CA stores are exposed read-only without a profile line.

OpenSSL reads them from C, out of the Python guards' sight, but not out of the OS
providers': under firejail or qemu an HTTPS request failed with "certificate verify
failed" until the profile exposed them. Their location depends on the distribution,
and an expose rule on a missing path is a configuration error, so only the stores
present on the host are added.
"""

from pathlib import Path

import pytest

from pysandboxes import guard_files
from pysandboxes.guard_files import FSExposeRule, parse_rules
from pysandboxes.main_logger import ErrorMsg


def _implicit_ca_rules() -> list[FSExposeRule]:
    errors: list[ErrorMsg] = []
    file_rules, _ = parse_rules([], errors)
    assert not errors
    return [r for r in file_rules if isinstance(r, FSExposeRule) and r.config.rule == "<ca-certificates>"]


def test_present_stores_are_exposed_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "certs"
    store.mkdir()
    monkeypatch.setattr(guard_files, "_CA_STORES", (str(store) + "/", str(tmp_path / "missing") + "/"))

    rules = _implicit_ca_rules()

    assert [(r.path, r.write) for r in rules] == [(str(store) + "/", False)]


def test_no_store_on_the_host_adds_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_files, "_CA_STORES", (str(tmp_path / "missing") + "/",))

    assert _implicit_ca_rules() == []
