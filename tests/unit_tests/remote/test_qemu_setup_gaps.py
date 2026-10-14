# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The guest bootstrap script built from the mounts, the config location and the working directory."""

import pytest

from pysandboxes.remote.qemu_setup import _bootstrap_script_content


def _script(**kwargs: object) -> list[str]:
    arguments: dict[str, object] = {"mounts": [], "pipe_run_guest_path": "/run/x", "python_version": "3.13"}
    arguments.update(kwargs)
    return _bootstrap_script_content(**arguments).splitlines()  # type: ignore[arg-type]


@pytest.mark.parametrize(("verbose", "shell_flags"), [(True, "set -ex"), (False, "set -e")])
def test_the_shell_traces_its_commands_only_when_asked(verbose: bool, shell_flags: str) -> None:
    assert _script(bootstrap_verbose=verbose)[1] == shell_flags


def test_the_file_rule_shares_are_mounted_only_when_there_are_some() -> None:
    assert "echo '[pysandbox-9p] mounting file_rules shares' >&2" in _script(mounts=[("tag1", "/a")])
    assert "echo '[pysandbox-9p] mounting file_rules shares' >&2" not in _script()


def test_the_mounts_feed_the_python_path_and_the_working_directory() -> None:
    script = _script(mounts=[("tag1", "/a"), ("tag2", "/b")])

    assert (
        'env PYTHONPATH=/a:/b "$PYTHON_EXE" -u -m pysandboxes.remote.main_sandbox --_named-pipe "$CONFIG_PATH"'
        in script
    )
    assert 'cd "/a" || true' in script


def test_without_mounts_the_python_path_is_empty_and_the_directory_is_the_root() -> None:
    script = _script()

    assert 'env "$PYTHON_EXE" -u -m pysandboxes.remote.main_sandbox --_named-pipe "$CONFIG_PATH"' in script
    assert 'cd "/" || true' in script


def test_a_given_working_directory_wins_over_the_first_mount() -> None:
    assert 'cd "/work" || true' in _script(mounts=[("tag1", "/a")], guest_cwd="/work")


def test_the_config_comes_from_the_shared_directory_when_it_is_given_else_from_the_pipe() -> None:
    shared = _script(config_guest_path="/cfg/config.pkl")
    piped = _script()

    assert 'CONFIG_PATH="/cfg/config.pkl"' in shared
    assert not any(line.startswith("PIPE_NAME=") for line in shared)
    assert 'CONFIG_PATH=/run/x/"$PIPE_NAME"' in piped
    assert any(line.startswith("PIPE_NAME=") for line in piped)
