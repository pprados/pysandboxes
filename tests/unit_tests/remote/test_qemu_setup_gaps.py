# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The guest bootstrap script built from the mounts, the config location and the working directory."""

import shlex

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
    assert "cd -- /a || _pysb_fatal 'cannot enter guest working directory'" in script


def test_without_mounts_the_python_path_is_empty_and_the_directory_is_the_root() -> None:
    script = _script()

    assert 'env "$PYTHON_EXE" -u -m pysandboxes.remote.main_sandbox --_named-pipe "$CONFIG_PATH"' in script
    assert "cd -- / || _pysb_fatal 'cannot enter guest working directory'" in script


def test_a_given_working_directory_wins_over_the_first_mount() -> None:
    assert "cd -- /work || _pysb_fatal 'cannot enter guest working directory'" in _script(
        mounts=[("tag1", "/a")], guest_cwd="/work"
    )


def test_a_working_directory_with_shell_metacharacters_is_quoted_not_injected() -> None:
    """A host mount path with a quote or a newline must not inject shell commands in the guest.

    Regression for a cwd interpolated unquoted into `cd "{guest_cwd}"`, reachable whenever
    config_guest_path was not the microvm pickle path (the default pipe-based channel, and the
    qemu `config_dir` channel).
    """
    injected_cwd = '/a"; touch /tmp/pwned; echo "'
    script = _script(guest_cwd=injected_cwd)

    assert not any(line.strip() == "touch /tmp/pwned" for line in script)
    quoted = shlex.quote(injected_cwd)
    assert f"mkdir -p -- {quoted} || _pysb_fatal 'cannot prepare guest working directory'" in script
    assert f"cd -- {quoted} || _pysb_fatal 'cannot enter guest working directory'" in script


def test_the_config_comes_from_the_shared_directory_when_it_is_given_else_from_the_pipe() -> None:
    shared = _script(config_guest_path="/cfg/config.pkl")
    piped = _script()

    assert 'CONFIG_PATH="/cfg/config.pkl"' in shared
    assert not any(line.startswith("PIPE_NAME=") for line in shared)
    assert 'CONFIG_PATH=/run/x/"$PIPE_NAME"' in piped
    assert any(line.startswith("PIPE_NAME=") for line in piped)
