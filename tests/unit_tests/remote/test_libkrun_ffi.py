# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Unit tests for pysandboxes.remote.libkrun_ffi."""

import ctypes
import unittest.mock
import pytest

from pysandboxes.remote.libkrun_ffi import (
    KrunBytes,
    KrunStr,
    LibkrunFFI,
    check_krun_result,
    find_libkrun,
    find_libkrunfw,
    make_krun_bytes,
    make_krun_str,
)


def test_make_krun_str() -> None:
    """Test string conversion to KrunStr."""
    kstr, buf = make_krun_str("hello_krun")
    assert isinstance(kstr, KrunStr)
    assert kstr.len == 10
    assert kstr.to_str() == "hello_krun"
    assert buf == b"hello_krun"


def test_make_krun_str_empty() -> None:
    """Test empty string conversion."""
    kstr, _ = make_krun_str("")
    assert kstr.len == 0
    assert kstr.to_str() == ""


def test_make_krun_bytes() -> None:
    """Test bytes conversion to KrunBytes."""
    data = b"\x01\x02\x03\x04"
    kbytes, buf = make_krun_bytes(data)
    assert isinstance(kbytes, KrunBytes)
    assert kbytes.len == 4
    assert buf == data


def test_check_krun_result_success() -> None:
    """Test check_krun_result with success."""
    mock_lib = unittest.mock.MagicMock()
    # Should not raise
    check_krun_result(mock_lib, 0, ctypes.c_void_p(0), "test_action")


def test_check_krun_result_failure() -> None:
    """Test check_krun_result with non-zero return code."""
    mock_lib = unittest.mock.MagicMock()
    with pytest.raises(RuntimeError, match="libkrun failed during test_action \\(return code: 42\\)"):
        check_krun_result(mock_lib, 42, ctypes.c_void_p(0), "test_action")


def test_find_libkrun_on_system() -> None:
    """Verify that libkrun is found on the system if installed."""
    lib = find_libkrun()
    assert lib is not None, "libkrun should be installed on this test host"


def test_find_libkrunfw_on_system() -> None:
    """Verify that libkrunfw is found on the system if installed."""
    fw = find_libkrunfw()
    assert fw is not None, "libkrunfw should be installed on this test host"


def test_libkrun_ffi_instantiation() -> None:
    """Verify LibkrunFFI initializes properly and exposes ctypes bindings."""
    ffi = LibkrunFFI()
    assert ffi.lib is not None
    assert hasattr(ffi.lib, "krun_vmm_builder_new")
    assert hasattr(ffi.lib, "krun_payload_load_krunfw")
    assert hasattr(ffi.lib, "krun_vmm_run")


def test_libkrun_ffi_not_found() -> None:
    """Verify LibkrunFFI raises RuntimeError when library cannot be located."""
    with unittest.mock.patch("pysandboxes.remote.libkrun_ffi.find_libkrun", return_value=None):
        with pytest.raises(RuntimeError, match="libkrun shared library not found"):
            LibkrunFFI()
