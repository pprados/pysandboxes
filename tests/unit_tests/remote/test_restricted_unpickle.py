# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Transport guards on the untrusted child->parent SSE channel.

Covers the restricted unpickler wired in base_sse_daemon.py on the exception and
result channels: opcode prescan, find_class predicates, the tblib shape guard,
and the profile switch.
"""

import base64
import collections
import copyreg
import dataclasses
import datetime
import decimal
import enum
import fractions
import functools
import importlib
import ipaddress
import math
import operator
import pathlib
import pickle
import subprocess
import sys
import time
import uuid
import zoneinfo
from collections.abc import Callable

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import RestrictedUnpicklingError, SandBoxProtocolError, sandbox_denials
from pysandboxes.learning import _update_remote_result_mode
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote import tools
from pysandboxes.remote.tools import (
    _ALLOWED_OPCODES,
    _MAX_BYTES,
    _SSE_LINE_LIMIT,
    SSE_READ_BUFSIZE,
    check_sse_line,
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
    """Serialize a payload the way the child does.

    The real server pickles the exception directly (sse_server_daemon.py)
    rather than going through ``to_b85``, so tests do the same.
    """
    return base64.b85encode(pickle.dumps(obj, protocol=5)).decode("ascii")


def _reduce_stream(module: str, name: str, args: tuple) -> str:
    """Build `module.name(*args)` as a pickle stream, the way a hostile child can write it by hand."""
    out = b"\x80\x05"
    for text in (module, name):
        out += pickle.SHORT_BINUNICODE + bytes([len(text)]) + text.encode()
    out += pickle.STACK_GLOBAL + pickle.MARK
    for arg in args:
        raw = arg if isinstance(arg, bytes) else arg.encode()
        out += (pickle.BINBYTES if isinstance(arg, bytes) else pickle.BINUNICODE) + len(raw).to_bytes(4, "little") + raw
    out += pickle.TUPLE + pickle.REDUCE + pickle.STOP
    return base64.b85encode(out).decode("ascii")


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

    @pytest.mark.parametrize(
        ("module", "name", "args"),
        [
            ("shutil", "rmtree", ("/nonexistent",)),
            ("shutil", "which", ("ls",)),
            ("io", "open", ("/nonexistent", "w")),
            ("_io", "FileIO", ("/nonexistent", "w")),
            ("signal", "getsignal", ("2",)),
            ("tempfile", "mkdtemp", ()),
            ("pickle", "loads", (pickle.dumps(len),)),
            ("types", "SimpleNamespace", ()),
            ("codecs", "open", ("/nonexistent", "w")),
            ("logging", "FileHandler", ("/nonexistent",)),
            ("builtins", "exit", ()),
            # A module re-exported as an attribute of an allowed one: the root of the stream's module is not the
            # module of the callable.
            ("pysandboxes.remote.tools", "os.system", ("echo pwned",)),
            ("pysandboxes.remote.tools", "shutil.rmtree", ("/nonexistent",)),
            # A method reached through an allowed class: called with an instance the stream builds.
            ("pathlib", "Path.unlink", ()),
            ("pathlib", "Path.write_text", ()),
        ],
    )
    def test_parent_side_gadgets_refused(
        self, module: str, name: str, args: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The unit-test fixture drops modules from sys.modules; the parent has them loaded, so the predicate must
        # be what refuses, not the "not loaded" check.
        monkeypatch.setitem(sys.modules, module, importlib.import_module(module))
        with pytest.raises(RestrictedUnpicklingError, match="is refused by the sandbox transport guard"):
            from_b85_restricted(_reduce_stream(module, name, args), result_predicate)

    def test_callable_imported_into_an_allowed_module_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # `from shutil import rmtree` in a loaded module: the stream names that module, the callable is shutil's.
        tools.rmtree_alias = __import__("shutil").rmtree  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pysandboxes.remote.tools", tools)
        try:
            with pytest.raises(RestrictedUnpicklingError, match="refused"):
                from_b85_restricted(
                    _reduce_stream("pysandboxes.remote.tools", "rmtree_alias", ("/nonexistent",)), result_predicate
                )
        finally:
            del tools.rmtree_alias  # type: ignore[attr-defined]

    def test_nested_class_still_resolves(self) -> None:
        assert from_b85_restricted(_hostile(_Outer.Inner("x")), exception_predicate).args == ("x",)

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

    def test_data_only_accepts_primitive_structures(self) -> None:
        value = {"items": [1, "two", (False, b"three")], "tags": frozenset({"a", "b"})}
        assert from_b85_restricted(to_b85(value), result_predicate, data_only=True) == value

    @pytest.mark.parametrize(
        "value",
        [
            pathlib.Path("/tmp/x"),
            pathlib.PurePosixPath("a/b"),
            pathlib.PureWindowsPath("c:/x"),
            datetime.datetime(2020, 1, 1, 12, tzinfo=datetime.timezone(datetime.timedelta(hours=2))),
            datetime.date(2020, 1, 1),
            datetime.time(1, 2),
            datetime.timedelta(seconds=3),
            decimal.Decimal("1.5"),
            uuid.UUID("12345678-1234-5678-1234-567812345678"),
            {"when": [datetime.date(2020, 1, 1)], "id": (uuid.UUID(int=1), pathlib.Path("p"))},
            zoneinfo.ZoneInfo("Europe/Paris"),
            datetime.datetime(2020, 1, 1, tzinfo=zoneinfo.ZoneInfo("Europe/Paris")),
            fractions.Fraction(1, 3),
            ipaddress.ip_address("10.0.0.1"),
            ipaddress.ip_address("::1"),
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("fe80::/64"),
            ipaddress.ip_interface("10.0.0.1/8"),
            ipaddress.ip_interface("fe80::1/64"),
            collections.OrderedDict(a=[1, pathlib.Path("x")]),
            collections.Counter("abca"),
            collections.deque([1, 2], maxlen=3),
            time.gmtime(0),
            range(1, 10, 2),
        ],
    )
    def test_data_only_accepts_value_types(self, value: object) -> None:
        assert from_b85_restricted(to_b85(value), result_predicate, data_only=True) == value

    def test_data_only_refuses_object_reconstruction(self) -> None:
        class ReturnedObject:
            def __reduce__(self) -> tuple:
                import os

                return (os.system, ("echo must-not-run",))

        with pytest.raises(RestrictedUnpicklingError, match="remote-result-mode=objects"):
            from_b85_restricted(to_b85(ReturnedObject()), result_predicate, data_only=True)

    @pytest.mark.parametrize(
        "make",
        [lambda: _Plain(1), lambda: _Point(1, 2), lambda: collections.OrderedDict(a=_Plain(1)), lambda: _Severity.HIGH],
    )
    def test_data_only_refuses_an_application_object(self, make: Callable[[], object]) -> None:
        with pytest.raises(RestrictedUnpicklingError, match="remote-result-mode=objects"):
            from_b85_restricted(to_b85(make()), result_predicate, data_only=True)

    @pytest.mark.parametrize(("target", "name"), [(pathlib.Path, "unlink"), (zoneinfo.ZoneInfo, "clear_cache")])
    def test_data_only_getattr_reaches_only_the_zoneinfo_constructor(self, target: type, name: str) -> None:
        with pytest.raises(RestrictedUnpicklingError, match="refused"):
            tools._value_getattr(target, name)

    def test_data_only_refuses_a_method_of_a_value_class(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "pathlib", pathlib)
        with pytest.raises(RestrictedUnpicklingError, match="pathlib.Path.unlink is refused"):
            from_b85_restricted(_reduce_stream("pathlib", "Path.unlink", ()), None, data_only=True)

    def test_learning_sees_value_types_as_data_only(self) -> None:
        assert not tools.result_requires_objects(to_b85({"p": pathlib.Path("/x"), "u": uuid.UUID(int=1)}))
        assert tools.result_requires_objects(to_b85(_Plain(1)))

    def test_data_only_refuses_cycles(self) -> None:
        value: list[object] = []
        value.append(value)
        with pytest.raises(RestrictedUnpicklingError, match="cyclic values"):
            from_b85_restricted(to_b85(value), result_predicate, data_only=True)

    def test_learning_recommends_objects_and_comments_the_previous_mode(self) -> None:
        lines = ["remote-result-mode=data-only"]
        generated = _update_remote_result_mode(
            lines,
            {"remote-result-mode=data-only", "remote-result-mode=objects"},
            "# Add rules (2026/10/02 at 12:34)",
        )
        assert "WARNING" in generated
        assert generated.endswith("remote-result-mode=objects")
        assert lines == [
            "# Previous mode superseded by learning on 2026/10/02 at 12:34:",
            "# remote-result-mode=data-only",
        ]

    def test_learning_recommends_data_only_when_no_objects_were_observed(self) -> None:
        assert (
            _update_remote_result_mode([], {"remote-result-mode=data-only"}, "# Add rules (date)")
            == "remote-result-mode=data-only"
        )

    def test_learning_does_not_add_duplicate_rules_for_an_unchanged_mode(self) -> None:
        lines = ["remote-result-mode=data-only"]
        assert _update_remote_result_mode(lines, {"remote-result-mode=data-only"}, "# Add rules (date)") == ""
        assert lines == ["remote-result-mode=data-only"]

    def test_learning_keeps_objects_mode_and_only_adds_its_warning(self) -> None:
        lines = ["remote-result-mode=objects"]
        generated = _update_remote_result_mode(lines, {"remote-result-mode=objects"}, "# Add rules (date)")
        assert "WARNING" in generated
        assert "remote-result-mode=" not in generated

    def test_learning_does_not_weaken_objects_mode_from_partial_observations(self) -> None:
        lines = ["remote-result-mode=objects"]
        assert _update_remote_result_mode(lines, {"remote-result-mode=data-only"}, "# Add rules (date)") == ""

    @pytest.mark.parametrize("observed", ["data-only", "objects"])
    def test_learning_never_duplicates_a_mode_set_by_an_included_profile(
        self, tmp_path: pathlib.Path, observed: str
    ) -> None:
        (tmp_path / ".py-sandboxes").write_text("remote-result-mode=data-only\n")
        learn_file = tmp_path / "tests.py-sandboxes"
        lines = ['include ".py-sandboxes"']
        generated = _update_remote_result_mode(
            lines, {f"remote-result-mode={observed}"}, "# Add rules (date)", learn_file
        )
        learn_file.write_text("\n".join([*lines, generated]))

        load_and_parse_config(learn_file, envs={})  # raised "Multiple remote-result-mode parameters"
        assert lines == ['include ".py-sandboxes"']


class _Severity(enum.Enum):
    LOW = 1
    HIGH = 2


_Point = collections.namedtuple("_Point", "x y")


@dataclasses.dataclass
class _Measure:
    label: str
    amount: decimal.Decimal
    at: datetime.datetime
    window: datetime.timedelta


@dataclasses.dataclass
class _Report:
    """Application object spanning the container and scalar types a result uses."""

    name: str
    severity: _Severity
    path: pathlib.Path
    ident: uuid.UUID
    measures: list[_Measure]
    index: dict[str, _Measure]
    tags: frozenset
    seen: set
    point: _Point
    blob: bytes
    raw: bytearray
    ratio: complex
    big: int
    history: collections.deque
    counts: collections.Counter
    ordered: collections.OrderedDict
    children: list = dataclasses.field(default_factory=list)


def _build_report(depth: int = 2, width: int = 3) -> _Report:
    measure = _Measure(
        label="latency",
        amount=decimal.Decimal("12.345"),
        at=datetime.datetime(2026, 9, 16, 10, 30, tzinfo=datetime.timezone.utc),
        window=datetime.timedelta(seconds=90),
    )
    report = _Report(
        name=f"level-{depth}",
        severity=_Severity.HIGH,
        path=pathlib.Path("/tmp/report.json"),
        ident=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        # The same instance repeated: pickle memoizes it, so the round trip has
        # to preserve sharing, not merely equality.
        measures=[measure] * width,
        index={"latency": measure},
        tags=frozenset({"a", "b"}),
        seen={1, 2, 3},
        point=_Point(1.5, 2.5),
        blob=b"\x00\xff" * 10,
        raw=bytearray(b"raw"),
        ratio=complex(1, 2),
        big=2**500,
        history=collections.deque(["first", "second"]),
        counts=collections.Counter("abracadabra"),
        ordered=collections.OrderedDict(a=1, b=2),
    )
    if depth > 0:
        report.children.append(_build_report(depth - 1, width))
    return report


class TestComplexResults:
    """The result channel carries more than the scalars the samples return.

    The samples' own tools return `float` and `str` only, so nothing there
    exercises the denylist against a real application object, nor the memo.
    """

    def test_a_deep_application_object_is_not_mistaken_for_a_gadget(self) -> None:
        report = _build_report()

        restored = from_b85_restricted(to_b85(report), result_predicate)

        assert restored == report
        assert restored.severity is _Severity.HIGH
        assert restored.big == 2**500
        assert restored.counts["a"] == 5
        assert restored.point.x == 1.5

    @pytest.mark.parametrize("depth", [2, 20, 100], ids=["shallow", "deep", "very-deep"])
    def test_nesting_survives(self, depth: int) -> None:
        restored = from_b85_restricted(to_b85(_build_report(depth=depth)), result_predicate)

        walked = 0
        node = restored
        while node.children:
            node = node.children[0]
            walked += 1
        assert walked == depth

    def test_a_wide_container_survives(self) -> None:
        reports = [_build_report(depth=0) for _ in range(500)]

        restored = from_b85_restricted(to_b85(reports), result_predicate)

        assert len(restored) == 500
        assert all(isinstance(r, _Report) for r in restored)

    def test_shared_references_stay_shared(self) -> None:
        """Identity through the memo, not just equality: the guard must not break it."""
        measure = _Measure("m", decimal.Decimal("1"), datetime.datetime(2026, 1, 1), datetime.timedelta(0))
        payload = {"a": measure, "b": measure, "list": [measure, measure]}

        restored = from_b85_restricted(to_b85(payload), result_predicate)

        assert restored["a"] is restored["b"]
        assert restored["list"][0] is restored["a"]
        assert restored["list"][0] is restored["list"][1]

    def test_repeated_instances_inside_one_object_stay_shared(self) -> None:
        restored = from_b85_restricted(to_b85(_build_report(depth=0)), result_predicate)

        assert restored.measures[0] is restored.measures[1]
        assert restored.index["latency"] is restored.measures[0]


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


class _ReportError(Exception):
    """Exception whose state holds a deep application object."""

    def __init__(self, message: str, report: "_Report") -> None:
        super().__init__(message)
        self.report = report

    def __reduce__(self) -> tuple:
        return (self.__class__, (str(self), self.report))


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

    def test_a_deep_application_state_also_falls_back(self) -> None:
        """The refused state is an application object, not just a stdlib type."""
        from pysandboxes.remote.base_sse_daemon import _rebuild_remote_exception

        rich, fallback = _both_forms(
            _ReportError("deep state", _build_report(depth=20)),
            ["RuleApiPermissionError: denied"],
        )

        rebuilt = _rebuild_remote_exception(rich, fallback)

        assert type(rebuilt) is _ReportError
        assert str(rebuilt) == "deep state"
        assert sandbox_denials(rebuilt) == ["RuleApiPermissionError: denied"]
        assert not hasattr(rebuilt, "report")

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
        descriptor: tuple[str, str, str, list[str]] = ("builtins", "dict", "boom", [])

        rebuilt = rebuild_from_descriptor(descriptor, SandBoxProtocolError)

        assert type(rebuilt) is SandBoxProtocolError

    @pytest.mark.parametrize("name", ["SystemExit", "KeyboardInterrupt"])
    def test_the_fallback_refuses_what_the_rich_form_refuses(self, name: str) -> None:
        """Both paths key on Exception, so BaseException-only classes stay out.

        Otherwise the descriptor would be a way to forge the very classes
        exception_predicate excludes from the gadget set.
        """
        descriptor: tuple[str, str, str, list[str]] = ("builtins", name, "boom", [])

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
        """_SSE_LINE_LIMIT tracks the read_bufsize the transport pins."""
        assert _SSE_LINE_LIMIT == 8 * SSE_READ_BUFSIZE

    def test_every_transport_session_pins_the_read_buffer(self) -> None:
        """A session left on the aiohttp default would widen the line ceiling.

        aiohttp raised that default from 65536 to 262144 in 3.14, which is
        exactly the drift the budget above must not follow.
        """
        daemons = sorted(pathlib.Path(tools.__file__).parent.glob("*_sse_daemon.py"))
        assert daemons, "no SSE daemon found next to tools.py"
        for daemon in daemons:
            for line in daemon.read_text().splitlines():
                if "aiohttp.ClientSession(" in line:
                    assert "read_bufsize=SSE_READ_BUFSIZE" in line, f"{daemon.name}: {line.strip()}"

    def test_an_oversized_payload_is_refused_by_the_prescan(self) -> None:
        with pytest.raises(RestrictedUnpicklingError, match="transport budget"):
            from_b85_restricted(_hostile(b"x" * (_MAX_BYTES + 1)), result_predicate)

    def test_the_child_refuses_an_oversized_line_before_sending_it(self) -> None:
        """Checked on the child side: the parent's reader would name nothing."""
        with pytest.raises(SandBoxProtocolError, match="limit of the transport"):
            check_sse_line("x" * (_SSE_LINE_LIMIT + 1))

    def test_a_line_within_the_limit_passes(self) -> None:
        check_sse_line("x" * _SSE_LINE_LIMIT)


class _Plain:
    """Ordinary class: no __eq__, so instances compare by identity."""

    def __init__(self, value: int) -> None:
        self.value = value


@dataclasses.dataclass
class _Node:
    """Dataclass, hence a generated __eq__ that recurses through `peer`."""

    name: str
    peer: object = None


class TestSerializationWithoutRoundTripAssert:
    """to_b85 no longer reloads and compares, which rejected valid objects."""

    def test_an_object_without_eq_is_serializable(self) -> None:
        """`==` fell back to identity, so every ordinary instance was refused."""
        restored = from_b85_restricted(to_b85(_Plain(1)), result_predicate)

        assert restored.value == 1

    def test_a_self_referencing_object_is_serializable(self) -> None:
        """A cycle whose __eq__ recurses used to raise RecursionError."""
        node = _Node("n")
        node.peer = node

        restored = from_b85_restricted(to_b85(node), result_predicate)

        assert restored.peer is restored


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
