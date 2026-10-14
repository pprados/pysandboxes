# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Error rendering and denial collection, the default image path, KVM detection and the guest stderr tail."""

import io
import platform
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pysandboxes.e import (
    _DENIALS_ATTRIBUTE,
    RuleFileNotFoundError,
    RulePermissionError,
    attach_sandbox_denials,
    sandbox_denials,
)
from pysandboxes.remote import qemu_image
from pysandboxes.remote.qemu_guest_console_io import GuestStderrTail


class TestRuleErrors:
    def test_a_rule_message_alone_is_printed_as_is(self) -> None:
        assert str(RulePermissionError("expose-ro=/x is missing")) == "expose-ro=/x is missing"

    def test_a_filename_set_by_the_caller_keeps_the_rule_message(self) -> None:
        error = RuleFileNotFoundError("hidden by ignore=*.env")
        error.filename = "/srv/.env"

        assert str(error) == "hidden by ignore=*.env"

    def test_no_argument_prints_an_empty_message(self) -> None:
        assert str(RuleFileNotFoundError()) == ""

    def test_an_errno_error_keeps_the_standard_rendering(self) -> None:
        assert str(RuleFileNotFoundError(2, "No such file")) == "[Errno 2] No such file"


class TestDenials:
    def test_a_chain_without_a_refusal_records_nothing(self) -> None:
        error = ValueError("plain")

        attach_sandbox_denials(error)

        assert not hasattr(error, _DENIALS_ATTRIBUTE)
        assert sandbox_denials(error) == []

    def test_a_refusal_only_reachable_through_the_cause_is_recorded(self) -> None:
        error = ConnectionError("All connection attempts failed")
        error.__cause__ = RulePermissionError("refused by a rule")

        attach_sandbox_denials(error)

        assert sandbox_denials(error) == ["RulePermissionError: refused by a rule"]

    def test_a_refusal_in_the_cause_of_an_exception_is_recorded(self) -> None:
        try:
            try:
                raise RulePermissionError("refused by a rule")
            except RulePermissionError as refusal:
                raise ConnectionError("All connection attempts failed") from refusal
        except ConnectionError as wrapped:
            error = wrapped

        attach_sandbox_denials(error)

        assert getattr(error, _DENIALS_ATTRIBUTE) == ["RulePermissionError: refused by a rule"]
        assert sandbox_denials(error) == ["RulePermissionError: refused by a rule"]


class TestImageHelpers:
    def test_the_default_image_follows_the_given_or_the_host_architecture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "machine", lambda: "x86_64")

        host = qemu_image.get_default_image_path(python_version=(3, 12))
        given = qemu_image.get_default_image_path(python_version=(3, 12), arch="aarch64")

        assert host.name == qemu_image.get_default_image_filename((3, 12), "x86_64")
        assert given.name == qemu_image.get_default_image_filename((3, 12), "aarch64")
        assert host.name != given.name

    @pytest.mark.parametrize(
        ("exists", "readable", "available"), [(True, True, True), (True, False, False), (False, True, False)]
    )
    def test_kvm_is_available_when_the_device_exists_and_is_readable(
        self, monkeypatch: pytest.MonkeyPatch, exists: bool, readable: bool, available: bool
    ) -> None:
        device = MagicMock()
        device.exists.return_value = exists
        monkeypatch.setattr(qemu_image, "Path", lambda *args: device)
        monkeypatch.setattr(qemu_image.os, "access", lambda path, mode: readable)

        assert qemu_image.is_kvm_available() is available


class TestGuestStderrTail:
    def test_the_thread_is_a_daemon_that_is_joined_on_exit(self, tmp_path: Path) -> None:
        tail = GuestStderrTail(tmp_path / "stderr", out=io.StringIO(), interval_s=0.01)

        with tail:
            thread = tail._thread
            assert thread is not None
            assert thread.daemon is True
            assert thread.is_alive()

        assert not thread.is_alive()

    def test_leaving_without_entering_is_harmless_and_drains_what_the_guest_wrote(self, tmp_path: Path) -> None:
        stderr = tmp_path / "stderr"
        stderr.write_text("guest says hello\n")
        out = io.StringIO()

        GuestStderrTail(stderr, out=out).__exit__(None, None, None)

        assert out.getvalue() == "guest says hello\n"
