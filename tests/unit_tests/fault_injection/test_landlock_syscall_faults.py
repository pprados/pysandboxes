# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The kernel refuses a Landlock call: creating or enforcing the ruleset is fatal, a lone rule is reported."""

import errno
import logging

import pytest

from pysandboxes.remote import landlock_daemon as ll

from ..remote.test_landlock_gaps import _Recorder

_ERRNOS = [errno.ENOSYS, errno.EPERM, errno.EINVAL, errno.EACCES, errno.ENOMEM, errno.E2BIG, errno.EMFILE]


@pytest.fixture(params=_ERRNOS, ids=errno.errorcode.get)
def kernel_errno(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(ll.ctypes, "get_errno", lambda: request.param)
    return int(request.param)


def test_a_ruleset_the_kernel_cannot_create_stops_the_start_with_its_errno(
    monkeypatch: pytest.MonkeyPatch, kernel_errno: int
) -> None:
    _Recorder(monkeypatch, abi=4, create_result=-1)

    with pytest.raises(OSError) as error:
        ll._apply_landlock([("/abs", False)])

    assert error.value.errno == kernel_errno


def test_a_ruleset_the_kernel_will_not_enforce_stops_the_start_with_its_errno(
    monkeypatch: pytest.MonkeyPatch, kernel_errno: int
) -> None:
    recorder = _Recorder(monkeypatch, abi=4, restrict_result=-1)

    with pytest.raises(OSError) as error:
        ll._apply_landlock([("/abs", False)])

    assert error.value.errno == kernel_errno
    assert [name for name, _ in recorder.calls][-1] == "restrict"


def test_a_ruleset_descriptor_is_closed_whatever_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder(monkeypatch, abi=4, restrict_result=-1)

    with pytest.raises(OSError):
        ll._apply_landlock([("/abs", False)])

    closed = [call.args[0] for call in recorder.libc.close.call_args_list]
    assert 7 in closed


def test_a_rule_the_kernel_refuses_is_reported_with_its_errno_and_the_others_still_apply(
    monkeypatch: pytest.MonkeyPatch, kernel_errno: int, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = _Recorder(monkeypatch, abi=4, add_result=-1)

    with caplog.at_level(logging.WARNING, logger=ll.logger.name):
        ll._apply_landlock([("/abs/one", False), ("/abs/two", True)])

    refused = [r.getMessage() for r in caplog.records if "landlock_add_rule" in r.getMessage()]
    assert any("/abs/one" in m and f"errno {kernel_errno}" in m for m in refused)
    assert any("/abs/two" in m for m in refused)
    assert [name for name, _ in recorder.calls][-1] == "restrict"
