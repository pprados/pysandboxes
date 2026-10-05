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
    with pytest.raises(RuntimeError, match="iptables-restore not found"):
        main_sandbox._apply_netfilter(RULES)


def test_rejected_rules_stop_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = _fake_restore(tmp_path, "echo 'Permission denied (you must be root)' >&2; exit 4")
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(script),))
    with pytest.raises(RuntimeError, match="Permission denied"):
        main_sandbox._apply_netfilter(RULES)


def test_applied_rules_reach_iptables_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    received = tmp_path / "received"
    script = _fake_restore(tmp_path, f'[ "$1" = --noflush ] && cat >"{received}"')
    monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", (str(tmp_path / "absent"), str(script)))
    main_sandbox._apply_netfilter(RULES)
    assert received.read_text() == "\n".join(RULES)
