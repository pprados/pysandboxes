# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The shipped configuration constants: a debug trace or a dropped wrapper must never ship by accident."""

from pysandboxes import config


def test_debug_traces_are_off_by_default() -> None:
    assert config.DEBUG is False


def test_the_profile_is_named_after_the_documented_file() -> None:
    assert config.CONFIG_NAME == ".py-sandboxes"
