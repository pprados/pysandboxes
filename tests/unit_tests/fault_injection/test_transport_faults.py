# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""A payload damaged on the child to parent channel: it must be refused, never half-accepted."""

import base64
import pickle
from typing import Any

import pytest

from pysandboxes.remote.tools import RestrictedUnpicklingError, from_b85_restricted

_VALUE = {"a": [1, 2.5, "x", b"y", None, True], "b": {"c": (1, 2)}}
_DATA = pickle.dumps(_VALUE, protocol=4)


def _encode(data: bytes) -> str:
    return base64.b85encode(data).decode()


def _deny_all(module: str, name: str, obj: Any) -> bool:
    return False


_MODES = [
    pytest.param(None, False, id="standard-load"),
    pytest.param(_deny_all, False, id="objects"),
    pytest.param(_deny_all, True, id="data-only"),
]


@pytest.mark.parametrize(("predicate", "data_only"), _MODES)
def test_the_intact_payload_is_accepted(predicate: Any, data_only: bool) -> None:
    assert from_b85_restricted(_encode(_DATA), predicate, data_only=data_only) == _VALUE


@pytest.mark.parametrize(("predicate", "data_only"), _MODES)
def test_a_payload_cut_anywhere_is_refused_with_the_transport_error(predicate: Any, data_only: bool) -> None:
    for cut in range(len(_DATA)):
        with pytest.raises(RestrictedUnpicklingError):
            from_b85_restricted(_encode(_DATA[:cut]), predicate, data_only=data_only)


@pytest.mark.parametrize("garbage", ["", "!!!!", "zz"])
def test_a_payload_that_is_not_base85_is_refused_with_the_transport_error(garbage: str) -> None:
    with pytest.raises(RestrictedUnpicklingError):
        from_b85_restricted(garbage, _deny_all)


@pytest.mark.xfail(strict=True, reason="a non-ASCII payload surfaces a bare UnicodeEncodeError from `str.encode`")
def test_a_payload_with_a_non_ascii_character_is_refused_with_the_transport_error() -> None:
    with pytest.raises(RestrictedUnpicklingError):
        from_b85_restricted("\u00e9", _deny_all)


@pytest.mark.xfail(
    strict=True,
    reason="a flipped bit can surface a bare ValueError, OverflowError, AttributeError or TypeError from the unpickler",
)
@pytest.mark.parametrize("data_only", [False, True])
def test_a_payload_with_a_flipped_bit_is_refused_or_loaded_but_never_leaks_a_bare_error(data_only: bool) -> None:
    for index in range(len(_DATA)):
        for bit in (0x01, 0x80):
            damaged = bytearray(_DATA)
            damaged[index] ^= bit
            try:
                from_b85_restricted(_encode(bytes(damaged)), _deny_all, data_only=data_only)
            except (RestrictedUnpicklingError, pickle.UnpicklingError):
                pass
