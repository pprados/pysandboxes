# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""ctypes foreign function interface for the libkrun micro-VM library.

This module provides ctypes bindings, struct definitions, and lifecycle
helpers to communicate with libkrun.so.2 and libkrunfw.so.5.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os

logger = logging.getLogger(__name__)

__all__ = [
    "KrunBytes",
    "KrunStr",
    "LibkrunFFI",
    "check_krun_result",
    "find_libkrun",
    "find_libkrunfw",
    "make_krun_bytes",
    "make_krun_str",
]


class KrunStr(ctypes.Structure):
    """UTF-8 string view passed across the libkrun C-ABI boundary."""

    _fields_ = [
        ("data", ctypes.c_char_p),
        ("len", ctypes.c_size_t),
    ]

    def to_str(self) -> str:
        """Convert KrunStr to Python string."""
        if not self.data or self.len == 0:
            return ""
        return ctypes.string_at(self.data, self.len).decode("utf-8", errors="replace")


class KrunBytes(ctypes.Structure):
    """Raw byte buffer view passed across the libkrun C-ABI boundary."""

    _fields_ = [
        ("data", ctypes.c_char_p),
        ("len", ctypes.c_size_t),
    ]


def make_krun_str(text: str) -> tuple[KrunStr, bytes]:
    """Create a KrunStr holding a pointer to a persistent bytes buffer.

    Returns a tuple (krun_str, raw_bytes) where raw_bytes must be kept alive
    as long as krun_str is accessed.
    """
    raw = text.encode("utf-8")
    return KrunStr(data=raw, len=len(raw)), raw


def make_krun_bytes(data: bytes) -> tuple[KrunBytes, bytes]:
    """Create a KrunBytes holding a pointer to a persistent bytes buffer."""
    return KrunBytes(data=data, len=len(data)), data


def find_libkrun() -> str | None:
    """Locate the libkrun shared library file path on the host."""
    common_paths = [
        "/usr/local/lib/libkrun.so",
        "/usr/local/lib/libkrun.so.2",
        "/usr/lib/libkrun.so",
        "/usr/lib/libkrun.so.2",
        "/usr/lib/x86_64-linux-gnu/libkrun.so",
        "/usr/lib/x86_64-linux-gnu/libkrun.so.2",
        "/usr/lib/aarch64-linux-gnu/libkrun.so",
        "/usr/lib/aarch64-linux-gnu/libkrun.so.2",
    ]
    for path in common_paths:
        if os.path.isfile(path):
            return path
    return ctypes.util.find_library("krun") or ctypes.util.find_library("krun.so.2")


def find_libkrunfw() -> str | None:
    """Locate the libkrunfw shared library file path on the host."""
    common_paths = [
        "/usr/local/lib/libkrunfw.so",
        "/usr/local/lib/libkrunfw.so.5",
        "/usr/lib/libkrunfw.so",
        "/usr/lib/libkrunfw.so.5",
        "/usr/lib/x86_64-linux-gnu/libkrunfw.so",
        "/usr/lib/x86_64-linux-gnu/libkrunfw.so.5",
        "/usr/lib/x86_64-linux-gnu/libkrunfw.so.5.5.0",
        "/usr/lib/aarch64-linux-gnu/libkrunfw.so",
        "/usr/lib/aarch64-linux-gnu/libkrunfw.so.5",
    ]
    for path in common_paths:
        if os.path.isfile(path):
            return path
    return ctypes.util.find_library("krunfw") or ctypes.util.find_library("krunfw.so.5")


def check_krun_result(lib: ctypes.CDLL, res: int, err: ctypes.c_void_p, action: str) -> None:
    """Check a libkrun function return code and raise a RuntimeError on failure."""
    if err and err.value:
        msg = f"libkrun error during {action}"
        try:
            lib.krun_error_message.argtypes = [ctypes.c_void_p]
            lib.krun_error_message.restype = KrunStr
            err_str = lib.krun_error_message(err)
            msg += f": {err_str.to_str()}"
            lib.krun_error_destroy.argtypes = [ctypes.c_void_p]
            lib.krun_error_destroy(err)
        except Exception:
            pass
        raise RuntimeError(msg)
    if res != 0:
        raise RuntimeError(f"libkrun failed during {action} (return code: {res})")


class LibkrunFFI:
    """Loaded and typed libkrun dynamic library wrapper."""

    def __init__(self, lib_path: str | None = None, fw_path: str | None = None) -> None:
        lib_path = lib_path or find_libkrun()
        if not lib_path:
            raise RuntimeError("libkrun shared library not found on the system")

        fw_path = fw_path or find_libkrunfw()
        if fw_path:
            # Preload libkrunfw into global namespace so libkrun dlopen finds it immediately
            try:
                ctypes.CDLL(fw_path, mode=ctypes.RTLD_GLOBAL)
            except OSError as e:
                logger.warning("Failed to preload libkrunfw from %s: %s", fw_path, e)

        self._lib = ctypes.CDLL(lib_path)
        self._setup_bindings()

    @property
    def lib(self) -> ctypes.CDLL:
        """Return the underlying ctypes.CDLL handle."""
        return self._lib

    def _setup_bindings(self) -> None:
        """Configure argtypes and restype for all bound libkrun C functions."""
        lib = self._lib

        # Logging
        lib.krun_init_log.argtypes = [
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        lib.krun_init_log.restype = ctypes.c_uint64

        # Error handling
        lib.krun_error_message.argtypes = [ctypes.c_void_p]
        lib.krun_error_message.restype = KrunStr
        lib.krun_error_destroy.argtypes = [ctypes.c_void_p]
        lib.krun_error_destroy.restype = None

        # Payload
        lib.krun_payload_load_krunfw.argtypes = [ctypes.c_void_p]
        lib.krun_payload_load_krunfw.restype = ctypes.c_void_p
        lib.krun_payload_append_cmdline.argtypes = [ctypes.c_void_p, KrunStr]
        lib.krun_payload_append_cmdline.restype = None
        lib.krun_payload_cmdline.argtypes = [ctypes.c_void_p]
        lib.krun_payload_cmdline.restype = KrunStr

        # VMM Builder
        lib.krun_vmm_builder_new.argtypes = []
        lib.krun_vmm_builder_new.restype = ctypes.c_void_p
        lib.krun_vmm_builder_vcpus.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_void_p]
        lib.krun_vmm_builder_vcpus.restype = ctypes.c_uint64
        lib.krun_vmm_builder_ram_mib.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        lib.krun_vmm_builder_ram_mib.restype = ctypes.c_uint64
        lib.krun_vmm_builder_payload.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.krun_vmm_builder_payload.restype = None
        lib.krun_vmm_builder_devices.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.krun_vmm_builder_devices.restype = None
        lib.krun_vmm_builder_build.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.krun_vmm_builder_build.restype = ctypes.c_void_p

        # VMM Execution
        lib.krun_vmm_run.argtypes = [ctypes.c_void_p]
        lib.krun_vmm_run.restype = None
        lib.krun_vmm_destroy.argtypes = [ctypes.c_void_p]
        lib.krun_vmm_destroy.restype = None

        # Devices: Device Manager
        lib.krun_mmio_device_manager_new.argtypes = []
        lib.krun_mmio_device_manager_new.restype = ctypes.c_void_p
        lib.krun_device_manager_add.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        lib.krun_device_manager_add.restype = ctypes.c_uint64

        # Devices: Filesystem (virtio-fs)
        lib.krun_fs_device_new.argtypes = [KrunStr, KrunStr, ctypes.c_void_p]
        lib.krun_fs_device_new.restype = ctypes.c_void_p
        lib.krun_fs_device_new_read_only.argtypes = [KrunStr, KrunStr, ctypes.c_void_p]
        lib.krun_fs_device_new_read_only.restype = ctypes.c_void_p

        # Devices: Console
        lib.krun_console_device_builder.argtypes = []
        lib.krun_console_device_builder.restype = ctypes.c_void_p
        lib.krun_console_builder_add_default_console.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        lib.krun_console_builder_add_default_console.restype = ctypes.c_uint64
        lib.krun_console_builder_build.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.krun_console_builder_build.restype = ctypes.c_void_p

        # Devices: Network (TAP)
        lib.krun_net_device_new_tap.argtypes = [
            KrunStr,
            KrunStr,
            KrunBytes,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        lib.krun_net_device_new_tap.restype = ctypes.c_void_p

        # Devices: Network (descriptor or socket of a user-space stack such as passt)
        lib.krun_net_device_new_unixstream_path.argtypes = [
            KrunStr,
            KrunStr,
            KrunBytes,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        lib.krun_net_device_new_unixstream_path.restype = ctypes.c_void_p
        lib.krun_net_device_new_unixstream_fd.argtypes = [
            KrunStr,
            ctypes.c_int,
            KrunBytes,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        lib.krun_net_device_new_unixstream_fd.restype = ctypes.c_void_p

        # Devices: Vsock
        lib.krun_vsock_device_new.argtypes = [ctypes.c_uint64, ctypes.c_uint32, ctypes.c_void_p]
        lib.krun_vsock_device_new.restype = ctypes.c_void_p
        lib.krun_vsock_device_add_unix_port.argtypes = [ctypes.c_void_p, ctypes.c_uint32, KrunStr, ctypes.c_bool]
        lib.krun_vsock_device_add_unix_port.restype = ctypes.c_uint64
