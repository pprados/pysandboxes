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
import inspect
import math
import operator
import pathlib
import pickle
import subprocess

import aiohttp
import pytest  # type: ignore[import-untyped]

from pysandboxes.e import RestrictedUnpicklingError, SandBoxProtocolError, sandbox_denials
from pysandboxes.remote.tools import (
    _ALLOWED_OPCODES,
    _MAX_BYTES,
    _SSE_LINE_LIMIT,
    describe_exception,
    descriptor_predicate,
    exception_predicate,
    from_b85_restricted,
    rebuild_from_descriptor,
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
            _rebuild_remote_exception(payload, None)


class _StatefulError(Exception):
    """Exception whose state holds an object the exception predicate refuses."""

    def __init__(self, message: str, path: pathlib.Path) -> None:
        super().__init__(message)
        self.path = path

    def __reduce__(self) -> tuple:
        return (self.__class__, (str(self), self.path))


def _both_forms(exc: BaseException, denials: list[str] | None = None) -> tuple[str, str]:
    """Serialize an exception the way the server does: rich form and descriptor."""
    import tblib

    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001
        tb = tblib.Traceback(caught.__traceback__)
        rich = _hostile((caught, tb))
        fallback = _hostile((describe_exception(caught, denials or []), tb))
    return rich, fallback


class TestDescriptorFallback:
    """The rich form is tried first; a refusal falls back to the descriptor.

    An exception's state routinely holds objects the predicate refuses, and
    losing the sandbox refusal matters more than losing those attributes.
    """

    def test_refused_rich_form_falls_back_to_the_descriptor(self) -> None:
        from pysandboxes.remote.base_sse_daemon import _rebuild_remote_exception

        rich, fallback = _both_forms(
            _StatefulError("refused", pathlib.Path("/tmp/x")),
            ["RulePermissionError: denied"],
        )
        # Without the fallback the refusal itself is what reaches the caller.
        with pytest.raises(RestrictedUnpicklingError):
            _rebuild_remote_exception(rich, None)

        rebuilt = _rebuild_remote_exception(rich, fallback)

        assert type(rebuilt) is _StatefulError
        assert str(rebuilt) == "refused"
        assert sandbox_denials(rebuilt) == ["RulePermissionError: denied"]
        assert not hasattr(rebuilt, "path"), "the descriptor form carries no state"

    def test_an_admissible_rich_form_keeps_its_state(self) -> None:
        from pysandboxes.remote.base_sse_daemon import _rebuild_remote_exception

        rich, fallback = _both_forms(ValueError("plain"))

        rebuilt = _rebuild_remote_exception(rich, fallback)

        assert type(rebuilt) is ValueError
        assert str(rebuilt) == "plain"

    def test_an_unpicklable_exception_still_reports_its_refusal(self) -> None:
        """The child sends "" when it cannot pickle the exception at all."""
        from pysandboxes.remote.base_sse_daemon import _rebuild_remote_exception

        _, fallback = _both_forms(ValueError("lost"), ["RuleFileNotFoundError: denied"])

        rebuilt = _rebuild_remote_exception("", fallback)

        assert type(rebuilt) is ValueError
        assert sandbox_denials(rebuilt) == ["RuleFileNotFoundError: denied"]

    def test_neither_form_is_a_refusal(self) -> None:
        from pysandboxes.remote.base_sse_daemon import _rebuild_remote_exception

        with pytest.raises(RestrictedUnpicklingError):
            _rebuild_remote_exception("", None)

    def test_an_unknown_class_degrades_instead_of_failing(self) -> None:
        """A class the parent never loaded must not swallow the refusal."""
        descriptor = ("no_such_module", "NoSuchError", "boom", ["RulePermissionError: denied"])

        rebuilt = rebuild_from_descriptor(descriptor, SandBoxProtocolError)

        assert type(rebuilt) is SandBoxProtocolError
        assert "no_such_module.NoSuchError" in str(rebuilt)
        assert sandbox_denials(rebuilt) == ["RulePermissionError: denied"]

    def test_a_non_exception_class_is_not_instantiated(self) -> None:
        """Resolving to dict must not let the stream build an arbitrary object."""
        descriptor = ("builtins", "dict", "boom", [])

        rebuilt = rebuild_from_descriptor(descriptor, SandBoxProtocolError)

        assert type(rebuilt) is SandBoxProtocolError

    @pytest.mark.parametrize("name", ["SystemExit", "KeyboardInterrupt"])
    def test_the_fallback_refuses_what_the_rich_form_refuses(self, name: str) -> None:
        """Both paths key on Exception, so BaseException-only classes stay out.

        Otherwise the descriptor would be a way to forge the very classes
        exception_predicate excludes from the gadget set.
        """
        descriptor = ("builtins", name, "boom", [])

        rebuilt = rebuild_from_descriptor(descriptor, SandBoxProtocolError)

        assert type(rebuilt) is SandBoxProtocolError
        assert name in str(rebuilt)

    @pytest.mark.parametrize(
        "descriptor",
        [
            ("too", "few"),
            ("mod", "name", "msg", "denials must be a list"),
            ("mod", "name", 42, []),
            ("mod", "name", "msg", [1, 2]),
        ],
        ids=["wrong-arity", "denials-not-a-list", "message-not-a-str", "denial-not-a-str"],
    )
    def test_a_malformed_descriptor_is_refused(self, descriptor: tuple) -> None:
        """The descriptor is child-controlled, so its shape is checked."""
        import tblib

        from pysandboxes.remote.base_sse_daemon import _rebuild_remote_exception

        try:
            raise ValueError("x")
        except ValueError as caught:
            payload = _hostile((descriptor, tblib.Traceback(caught.__traceback__)))

        with pytest.raises(RestrictedUnpicklingError):
            _rebuild_remote_exception("", payload)

    def test_the_descriptor_predicate_refuses_a_gadget(self) -> None:
        """The fallback payload carries primitives, so only tblib may resolve."""

        class Evil:
            def __reduce__(self) -> tuple:
                import os

                return (os.system, ("echo pwned",))

        with pytest.raises(RestrictedUnpicklingError):
            from_b85_restricted(_hostile(Evil()), descriptor_predicate)


class TestPayloadBudget:
    """The byte budget is derived from what the SSE line can actually carry."""

    def test_the_budget_fits_the_sse_line(self) -> None:
        """A payload at the budget must still encode to a line aiohttp accepts.

        The ceiling is the HTTP reader, not this budget: aiohttp caps a line at
        8 * read_bufsize. If either side moves, this reddens instead of failing
        in production as an opaque LineTooLong.
        """
        encoded = math.ceil(_MAX_BYTES / 4) * 5

        assert encoded < _SSE_LINE_LIMIT, "a payload at the budget would not fit the SSE line"
        # Room left on the line for the JSON envelope and captured stdout/stderr.
        assert _SSE_LINE_LIMIT - encoded >= 32 * 1024

    def test_the_budget_matches_the_client_read_buffer(self) -> None:
        """_SSE_LINE_LIMIT tracks the ClientSession default the transport uses."""
        default_read_bufsize = inspect.signature(aiohttp.ClientSession.__init__).parameters["read_bufsize"].default

        assert _SSE_LINE_LIMIT == 8 * default_read_bufsize

    def test_an_oversized_payload_is_refused_by_the_prescan(self) -> None:
        with pytest.raises(RestrictedUnpicklingError, match="transport budget"):
            from_b85_restricted(_hostile(b"x" * (_MAX_BYTES + 1)), result_predicate)


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
