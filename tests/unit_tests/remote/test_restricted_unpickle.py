# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Transport guards on the untrusted child->parent SSE channel.

Covers the restricted unpickler wired in base_sse_daemon.py on the exception and
result channels: opcode prescan, find_class predicates, the tblib shape guard,
and the profile switch.
"""

import base64
import copyreg
import datetime
import decimal
import functools
import operator
import pathlib
import pickle
import subprocess

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import RestrictedUnpicklingError
from pysandboxes.remote.tools import (
    _ALLOWED_OPCODES,
    exception_predicate,
    from_b85_restricted,
    result_predicate,
    to_b85,
)


class _Outer:
    """Host for a nested exception, to exercise dotted-qualname resolution."""

    class Inner(Exception):
        pass


def _hostile(obj: object) -> str:
    """Serialize a payload the way the child does, bypassing to_b85's assert.

    ``to_b85`` asserts a round-trip equals the original, which a hostile object
    (or an exception, lacking ``__eq__``) breaks. The real server pickles the
    exception directly (sse_server_daemon.py), so tests do the same.
    """
    return base64.b85encode(pickle.dumps(obj, protocol=5)).decode("ascii")


class TestResultChannel:
    """The result channel: denylist over a fail-open predicate."""

    def test_reduce_gadget_refused(self) -> None:
        class Evil:
            def __reduce__(self) -> tuple:
                import os

                return (os.system, ("echo pwned",))

        with pytest.raises(RestrictedUnpicklingError):
            from_b85_restricted(_hostile(Evil()), result_predicate)

    def test_eval_forged_class_refused(self) -> None:
        forged = eval("type('X',(),{'__reduce__':lambda s:(__import__('os').system,('x',))})()")
        with pytest.raises(RestrictedUnpicklingError):
            from_b85_restricted(_hostile(forged), result_predicate)

    @pytest.mark.parametrize(
        "gadget",
        [
            functools.partial(len),
            operator.attrgetter("x"),
            subprocess.Popen,
        ],
    )
    def test_classic_gadgets_refused(self, gadget: object) -> None:
        with pytest.raises(RestrictedUnpicklingError):
            from_b85_restricted(_hostile(gadget), result_predicate)

    def test_memo_indirection_refused(self) -> None:
        # os/system memoized then recalled via BINGET before STACK_GLOBAL: a
        # name-inventory prescan would miss it; find_class catches it.
        data = b"\x80\x05\x8c\x02os\x94\x8c\x06system\x94h\x00h\x01\x93\x94\x8c\x04date\x85\x94R\x94."
        with pytest.raises(RestrictedUnpicklingError):
            from_b85_restricted(base64.b85encode(data).decode(), result_predicate)

    @pytest.mark.parametrize(
        "value",
        [
            1,
            "s",
            b"bytes",
            {"a": 1, "b": [1, 2]},
            [1, 2, 3],
            (1, 2),
            pathlib.Path("/tmp"),
            datetime.datetime(2020, 1, 1),
            decimal.Decimal("1.5"),
        ],
    )
    def test_legit_results_roundtrip(self, value: object) -> None:
        assert from_b85_restricted(to_b85(value), result_predicate) == value


class TestPrescan:
    """Opcode allowlist and budgets, ahead of any execution."""

    def test_ext_opcode_refused(self) -> None:
        copyreg.add_extension("os", "system", 240)
        try:
            stream = b"\x80\x05\x82\xf0."  # PROTO 5, EXT1 240, STOP
            with pytest.raises(RestrictedUnpicklingError):
                from_b85_restricted(base64.b85encode(stream).decode(), result_predicate)
        finally:
            copyreg.remove_extension("os", "system", 240)

    def test_corpus_opcodes_within_allowlist(self) -> None:
        import pickletools

        cyclic: list = []
        cyclic.append(cyclic)
        samples = [
            1,
            "x" * 300,
            b"x" * 300,
            list(range(300)),
            {str(i): i for i in range(300)},
            2**500,
            bytearray(b"ab"),
            (1, 2, 3),
            {1, 2, 3},
            frozenset({1}),
            cyclic,
        ]
        for sample in samples:
            for opcode, _arg, _pos in pickletools.genops(pickle.dumps(sample, protocol=5)):
                assert opcode.name in _ALLOWED_OPCODES, opcode.name


class TestExceptionChannel:
    """The exception channel: fail-closed predicate."""

    def test_exception_predicate_accepts_all_e_classes(self) -> None:
        import pysandboxes.e as e

        for name in dir(e):
            obj = getattr(e, name)
            if isinstance(obj, type) and issubclass(obj, Exception):
                assert exception_predicate("pysandboxes.e", name, obj), name

    @pytest.mark.parametrize(
        "exc",
        [
            ValueError("boom"),
            _Outer.Inner("nested"),
        ],
    )
    def test_builtin_and_nested_exception_roundtrip(self, exc: BaseException) -> None:
        import tblib

        try:
            raise exc
        except BaseException as caught:  # noqa: BLE001
            tb = tblib.Traceback(caught.__traceback__)
            payload = _hostile((caught, tb))
        r_exc, r_tb = from_b85_restricted(payload, exception_predicate)
        assert type(r_exc) is type(exc)
        r_tb.as_traceback()

    def test_e_module_exceptions_roundtrip(self) -> None:
        import tblib

        from pysandboxes.e import ConfigSyntaxError, RuleApiPermissionError, RuleEvalPermissionError

        instances = [
            ConfigSyntaxError("msg", ["e1", "e2"]),
            RuleApiPermissionError("os.system", "process"),
            RuleEvalPermissionError("__globals__", "eval-magic"),
        ]
        for exc in instances:
            try:
                raise exc
            except BaseException as caught:  # noqa: BLE001
                tb = tblib.Traceback(caught.__traceback__)
                payload = _hostile((caught, tb))
            r_exc, _ = from_b85_restricted(payload, exception_predicate)
            assert type(r_exc) is type(exc)


class TestTblibShapeGuard:
    """The daemon-level guard on the traceback shape before as_traceback()."""

    def test_non_tblib_traceback_refused(self) -> None:
        from pysandboxes.remote.base_sse_daemon import _rebuild_remote_exception

        payload = _hostile((ValueError("x"), "not a traceback"))
        with pytest.raises(RestrictedUnpicklingError):
            _rebuild_remote_exception(payload)


class TestSwitch:
    """The profile switch disables only the result denylist, not the prescan."""

    def test_off_lets_denied_gadget_through(self) -> None:
        gadget = functools.partial(len)
        with pytest.raises(RestrictedUnpicklingError):
            from_b85_restricted(_hostile(gadget), result_predicate)
        # predicate=None models the switch off: the denylist no longer applies.
        result = from_b85_restricted(_hostile(gadget), None)
        assert isinstance(result, functools.partial)

    def test_off_keeps_prescan(self) -> None:
        copyreg.add_extension("os", "system", 241)
        try:
            stream = b"\x80\x05\x82\xf1."  # PROTO 5, EXT1 241, STOP
            with pytest.raises(RestrictedUnpicklingError):
                from_b85_restricted(base64.b85encode(stream).decode(), None)
        finally:
            copyreg.remove_extension("os", "system", 241)
