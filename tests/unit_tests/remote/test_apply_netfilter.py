# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The network filter of bwrap --unshare-net and of the QEMU guest fails closed.

A profile with socket rules relies on these iptables rules at the OS level. When they cannot be applied, the child
must stop rather than run with the network the rules were meant to restrict.
"""

from pathlib import Path

import pytest

from pysandboxes.remote import main_sandbox

RULES = ("*filter", "-A OUTPUT -j DROP", "COMMIT")


def _fake_restore(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "iptables-restore"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return script


def test_missing_iptables_restore_stops_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(tmp_path / "absent"),))
    with pytest.raises(RuntimeError, match="no executable iptables-restore"):
        main_sandbox._apply_netfilter(RULES)


def test_rejected_rules_stop_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = _fake_restore(tmp_path, "echo 'Permission denied (you must be root)' >&2; exit 4")
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(script),))
    with pytest.raises(RuntimeError, match="iptables-restore failed.*Permission denied"):
        main_sandbox._apply_netfilter(RULES)


def test_applied_rules_reach_iptables_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    received = tmp_path / "received"
    script = _fake_restore(tmp_path, f'[ "$1" = --noflush ] && cat >"{received}"')
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(tmp_path / "absent"), str(script)))
    main_sandbox._apply_netfilter(RULES)
    assert received.read_text() == "\n".join(RULES)


def test_a_looping_alternatives_link_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The host's /etc, exposed over the guest's, turns /usr/sbin/iptables-restore into a dead link."""
    loop = tmp_path / "iptables-restore-loop"
    loop.symlink_to(loop)
    received = tmp_path / "received"
    script = _fake_restore(tmp_path, f'cat >"{received}"')
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(loop), str(script)))
    main_sandbox._apply_netfilter(RULES)
    assert received.exists()


def test_a_candidate_that_is_not_executable_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = tmp_path / "iptables-nft-restore"
    plain.write_text("#!/bin/sh\nexit 0\n")
    plain.chmod(0o644)
    received = tmp_path / "received"
    script = _fake_restore(tmp_path, f'cat >"{received}"')
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(plain), str(script)))
    main_sandbox._apply_netfilter(RULES)
    assert received.read_text() == "\n".join(RULES)


def test_only_non_executable_candidates_stop_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = tmp_path / "iptables-restore"
    plain.write_text("#!/bin/sh\nexit 0\n")
    plain.chmod(0o644)
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(plain),))
    with pytest.raises(RuntimeError, match="no executable iptables-restore"):
        main_sandbox._apply_netfilter(RULES)


def test_the_next_candidate_is_tried_when_one_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    failing = _fake_restore(broken, "echo 'nft backend unavailable' >&2; exit 1")
    received = tmp_path / "received"
    working = _fake_restore(tmp_path, f'cat >"{received}"')
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(failing), str(working)))
    main_sandbox._apply_netfilter(RULES)
    assert received.read_text() == "\n".join(RULES)


def test_a_candidate_that_cannot_be_executed_is_followed_by_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_interpreter = tmp_path / "no-interpreter"
    no_interpreter.write_text("#!/nonexistent/interpreter\n")
    no_interpreter.chmod(0o755)
    received = tmp_path / "received"
    working = _fake_restore(tmp_path, f'cat >"{received}"')
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(no_interpreter), str(working)))
    main_sandbox._apply_netfilter(RULES)
    assert received.exists()


def test_every_candidate_failing_stops_the_child_with_the_last_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    one = _fake_restore(first, "echo first-error >&2; exit 2")
    two = _fake_restore(second, "echo second-error >&2; exit 3")
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(one), str(two)))
    with pytest.raises(RuntimeError, match=r"iptables-restore failed, .*second.*\(3\): second-error"):
        main_sandbox._apply_netfilter(RULES)


def test_the_backend_binaries_come_before_the_alternatives_link() -> None:
    paths = main_sandbox._IPTABLES_RESTORE_PATHS
    assert paths.index("/usr/sbin/iptables-nft-restore") < paths.index("/usr/sbin/iptables-restore")
    assert paths.index("/usr/sbin/iptables-legacy-restore") < paths.index("/usr/sbin/iptables-restore")
