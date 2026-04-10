# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests for QEMU nested lib staging mode (``qemu.ld_closure_libs``)."""

from pysandboxes.remote.qemu_sse_daemon import (
    _debian_multiarch_triplet,
    _normalize_ld_closure_libs_param,
)


def test_debian_multiarch_triplet_common_cpus() -> None:
    assert _debian_multiarch_triplet("x86_64") == "x86_64-linux-gnu"
    assert _debian_multiarch_triplet("aarch64") == "aarch64-linux-gnu"
    assert _debian_multiarch_triplet("armv7l") == "arm-linux-gnueabihf"


def test_normalize_ld_closure_libs_param_defaults_full() -> None:
    assert _normalize_ld_closure_libs_param(None) == "full"
    assert _normalize_ld_closure_libs_param("") == "full"
    assert _normalize_ld_closure_libs_param("full") == "full"
    assert _normalize_ld_closure_libs_param("multiarch") == "full"


def test_normalize_ld_closure_libs_param_sparse_aliases() -> None:
    assert _normalize_ld_closure_libs_param("sparse") == "sparse"
    assert _normalize_ld_closure_libs_param("minimal") == "sparse"
    assert _normalize_ld_closure_libs_param("ldd") == "sparse"
