# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`is_ambient`'s gateway walk: stdlib entry points that run caller-supplied code directly.

`importlib.abc.InspectLoader.source_to_code`, `SourceFileLoader.get_code`,
`code.InteractiveInterpreter.runsource`, `timeit.timeit` and `runpy.run_path` each reach
`compile`/`exec` from inside a stdlib frame, which the old single-frame `is_ambient` always
trusted. Calling one of them directly, with no `eval-*` rule declared and no
`python-api=ALLOW:dynamic-code` grant, used to run the application's own source unguarded; see
`wiki/weaknesses.md`. The integration tests below pin the fix behaviourally (the dangerous
`exec`/`compile` must not have run, not merely "an exception was raised": from Python 3.13
`runsource` catches `RuleApiPermissionError` the same broad way it catches a real `SyntaxError`). The pure tests pin
the walk itself against a synthetic frame chain, independent of any guard activation.
"""

import ast
import builtins
import code
import contextlib
import importlib.abc
import importlib.machinery
import inspect
import marshal
import os
import runpy
import sys
import sysconfig
import timeit
import types
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from pysandboxes import guard_api, guard_eval
from pysandboxes.e import RuleApiPermissionError
from pysandboxes.guard_eval import _GATEWAY_EXCLUSIONS, _GATEWAY_FILES, _GATEWAYS, is_ambient
from pysandboxes.guard_import import user_code
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.lifecycle import _reset_for_tests, arm

_STDLIB = str(Path(sysconfig.get_paths()["stdlib"]).resolve())


def _lib(rel: str) -> str:
    """An absolute path under the real stdlib root, for a frame that must resolve as stdlib."""
    return str(Path(_STDLIB) / rel)


def _frame_chain(*levels: tuple[str, str]) -> types.FrameType:
    """Build a real call chain stamped with `(filename, qualname)` pairs, outermost first.

    Returns the innermost frame, the one `is_ambient` receives as `sys._getframe(1)` from inside
    the builtin it guards. Each level is a real compiled function, so `f_back` genuinely climbs
    the chain `is_ambient` walks; `CodeType.replace(co_qualname=...)` stamps the qualname a
    one-line `def` cannot express (`SourceLoader.source_to_code`, a class.method pair) without
    writing out the class nesting for every table entry under test.
    """
    call_next: Callable[[], types.FrameType] | None = None
    for filename, qualname in reversed(levels):
        namespace: dict[str, Any] = {"_call_next": call_next, "sys": sys}
        src = (
            "def _level():\n    return sys._getframe()\n"
            if call_next is None
            else "def _level():\n    return _call_next()\n"
        )
        fn_code = compile(src, filename, "exec")
        exec(fn_code, namespace)  # noqa: S102
        fn = namespace["_level"]
        fn.__code__ = fn.__code__.replace(co_qualname=qualname)
        call_next = fn
    assert call_next is not None
    return call_next()


# ---------------------------------------------------------------- pure walk, synthetic frames


def test_a_direct_call_to_a_gateway_from_user_code_is_not_ambient() -> None:
    frame = _frame_chain(("/tmp/attacker.py", "<module>"), (_lib("importlib/abc.py"), "InspectLoader.source_to_code"))
    assert not is_ambient(frame)


def test_a_legitimate_import_through_the_frozen_source_to_code_chain_stays_ambient() -> None:
    """`get_code`/`source_to_code`/`_call_with_frames_removed` are frozen on a default build:
    `<frozen importlib._bootstrap_external>`, not a `.py` path -- the chain must still resolve
    through `_module_key`'s dotted-name normalisation, the same as the non-frozen form."""
    frame = _frame_chain(
        ("<frozen importlib._bootstrap>", "_find_and_load"),
        ("<frozen importlib._bootstrap_external>", "SourceLoader.get_code"),
        ("<frozen importlib._bootstrap_external>", "SourceLoader.source_to_code"),
        ("<frozen importlib._bootstrap>", "_call_with_frames_removed"),
    )
    assert is_ambient(frame)


def test_a_direct_call_to_get_code_from_user_code_is_not_ambient() -> None:
    """The hard case: every frame up to the real caller is frozen, unlike the legitimate chain
    above only in who is one level further up."""
    frame = _frame_chain(
        ("/tmp/attacker.py", "<module>"),
        ("<frozen importlib._bootstrap_external>", "SourceLoader.get_code"),
        ("<frozen importlib._bootstrap_external>", "SourceLoader.source_to_code"),
        ("<frozen importlib._bootstrap>", "_call_with_frames_removed"),
    )
    assert not is_ambient(frame)


def test_a_direct_call_into_a_whole_gateway_file_from_user_code_is_not_ambient() -> None:
    frame = _frame_chain(("/tmp/attacker.py", "<module>"), (_lib("timeit.py"), "Timer.__init__"))
    assert not is_ambient(frame)


def test_a_library_self_codegen_call_stays_ambient_regardless_of_its_caller() -> None:
    """`dataclasses._create_fn` is excluded on purpose: it runs a template the library built
    from validated field names, not the caller's source. Confirms the exclusion leaves the
    original per-frame rule (stdlib => ambient) in force, rather than refusing by omission."""
    frame = _frame_chain(("/tmp/attacker.py", "<module>"), (_lib("dataclasses.py"), "_create_fn"))
    assert is_ambient(frame)


def test_every_gateway_table_entry_is_well_formed() -> None:
    for module_key, qualname in _GATEWAYS:
        assert module_key.endswith(".py"), module_key
        assert qualname, module_key


def test_a_bare_string_tag_is_not_mistaken_for_a_frozen_module() -> None:
    """`<string>` ends with `>`, exactly like every frozen module name, but does not start with
    `<frozen `: a plain `exec(source)` with no filename argument stamps the caller's own code
    this way, so misreading it as frozen would make every later eval/exec/compile call from that
    frame wrongly ambient -- exempting the application itself, the one thing this guard exists to
    cover (see `is_ambient`'s own docstring on `<string>`)."""
    frame = _frame_chain(("<string>", "<module>"))
    assert not is_ambient(frame)


# ----------------------------------------------------------- framework's own `-m` dispatch


def _pysandboxes_file(*parts: str) -> str:
    """An absolute path to a real file under the pysandboxes package, for a frame that must
    resolve against `_FRAMEWORK_ROOT` the same way a genuine one does."""
    return str(Path(guard_eval.__file__).resolve().parent.joinpath(*parts))


def test_the_m_dispatch_chain_through_python_in_sb_and_main_sandbox_stays_ambient() -> None:
    """Pins the fix for the regression commit `02723db7` introduced: `_python_module` calls
    `runpy.run_module` directly instead of the frame-less C-level `-m` dispatch a plain
    `python -m pkg.mod` performs, so the entry module's `_compile_bytecode`/`marshal.loads` read
    of its own `.pyc` cache used to land on a non-stdlib pysandboxes frame (`_python_module`'s own)
    and be judged as if it were the application's own call site -- denying every `-m` launch under
    every OS provider with no `python-api=ALLOW:dynamic-code` grant."""
    python_in_sb_file = _pysandboxes_file("remote", "python_in_sb.py")
    main_sandbox_file = _pysandboxes_file("remote", "main_sandbox.py")
    frame = _frame_chain(
        # Stands in for "ran out of frames": in a real `-m pysandboxes.remote.main_sandbox`
        # launch, nothing but the frameless C-level interpreter entry sits above this chain. Any
        # stdlib, non-gateway frame terminates the synthetic walk the same way, as the other
        # tests in this file already rely on (e.g. the chain below ending at `_find_and_load`).
        ("<frozen importlib._bootstrap>", "_find_and_load"),
        (main_sandbox_file, "<module>"),
        (main_sandbox_file, "main"),
        (main_sandbox_file, "run_guest"),
        (python_in_sb_file, "python_in_sb"),
        (python_in_sb_file, "_python_module"),
        ("<frozen runpy>", "run_module"),
        ("<frozen runpy>", "_get_module_details"),
        ("<frozen importlib._bootstrap_external>", "SourceLoader.get_code"),
        ("<frozen importlib._bootstrap_external>", "_compile_bytecode"),
    )
    assert is_ambient(frame)


def test_the_m_dispatch_chain_is_denied_once_the_framework_gateway_table_is_emptied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control for the fix itself, not only for its scope: the exact chain the test
    above pins as ambient must stop being ambient once `_FRAMEWORK_GATEWAYS` is emptied,
    proving that table -- and not some other rule -- is what makes it so.

    Calling `_python_module` directly from a real frame (in-process or in a child process) is
    not a usable substitute: it always ends up denied, with or without `_FRAMEWORK_GATEWAYS`,
    because the caller then sitting above the dispatch chain (a test function, never frozen or
    in the table) is exactly the application's-own-call-site case
    `test_the_m_dispatch_gateway_keeps_climbing_past_itself_instead_of_concluding_there` covers;
    only a real `-m` launch has nothing but frozen import machinery there, which is what the
    synthetic chain below stands in for (see its own comment). An end-to-end launch proves the
    production table still works (`tests/unit_tests/remote/test_m_launch_regression.py`); this
    test isolates *why*.
    """
    python_in_sb_file = _pysandboxes_file("remote", "python_in_sb.py")
    main_sandbox_file = _pysandboxes_file("remote", "main_sandbox.py")
    frame = _frame_chain(
        ("<frozen importlib._bootstrap>", "_find_and_load"),
        (main_sandbox_file, "<module>"),
        (main_sandbox_file, "main"),
        (main_sandbox_file, "run_guest"),
        (python_in_sb_file, "python_in_sb"),
        (python_in_sb_file, "_python_module"),
        ("<frozen runpy>", "run_module"),
        ("<frozen runpy>", "_get_module_details"),
        ("<frozen importlib._bootstrap_external>", "SourceLoader.get_code"),
        ("<frozen importlib._bootstrap_external>", "_compile_bytecode"),
    )

    monkeypatch.setattr(guard_eval, "_FRAMEWORK_GATEWAYS", frozenset())

    assert not is_ambient(frame)


def test_a_different_python_in_sb_function_is_not_treated_as_the_m_dispatch_gateway() -> None:
    """Negative control: the exemption is scoped to the exact `-m` dispatch frames, not every
    function in `python_in_sb.py`. `_python_script`/`_python_command` already launch the user's
    code through the raw, unwrapped `exec`/`compile` captured before patching -- by design, never
    reaching this guard at all -- and must never need this exemption either."""
    python_in_sb_file = _pysandboxes_file("remote", "python_in_sb.py")
    frame = _frame_chain(
        (python_in_sb_file, "_python_script"),
        ("<frozen importlib._bootstrap_external>", "_compile_bytecode"),
    )
    assert not is_ambient(frame)


def test_a_non_dispatch_frame_under_the_package_root_is_still_judged_on_its_own() -> None:
    """`_framework_key(filename) is not None` alone must never be enough to keep climbing past a
    frame; only together with the exact `(key, qualname)` match. The frame handed to `is_ambient`
    is `_python_script` (under the package root, not one of the five dispatch qualnames); above
    it sits a frame the ordinary module-key rule alone would call ambient (a non-gateway frozen
    frame). Wrongly treating the first frame as a forwarding gateway would climb past it and
    conclude ambient there; judging it on its own, as the application's call site, concludes not
    ambient instead, without even reaching the frame above it."""
    python_in_sb_file = _pysandboxes_file("remote", "python_in_sb.py")
    frame = _frame_chain(("<frozen importlib._bootstrap>", "_find_and_load"), (python_in_sb_file, "_python_script"))
    assert not is_ambient(frame)


def test_the_m_dispatch_gateway_keeps_climbing_past_itself_instead_of_concluding_there() -> None:
    """A dispatch frame only forwards the climb to whoever is above it; it is never itself the
    answer. Stacking a frame above it that is unambiguously the application's own call site (an
    arbitrary non-stdlib path) must still be reached and judged, not skipped by concluding ambient
    right at the dispatch frame."""
    python_in_sb_file = _pysandboxes_file("remote", "python_in_sb.py")
    frame = _frame_chain(("/tmp/attacker.py", "<module>"), (python_in_sb_file, "_python_module"))
    assert not is_ambient(frame)


# ---------------------------------------------------------------- end-to-end, real activation


@pytest.fixture
def _armed_with_no_eval_rule_at_all(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch the builtins and `marshal` this module's wrappers touch, declaring no `eval-*`
    profile and no `python-api` grant at all: the configuration under which a gateway bypass
    used to run the application's own source unguarded.

    `guard_import.activate_guard_import` is not used here: the autouse `activate_guard` fixture
    (`tests/unit_tests/conftest.py`) already activated it, for the whole session, with only the
    file/socket/import patches -- never guard_eval's or guard_api's -- so a second call is a
    silent no-op (`guard_import._activated` is already `True`). `monkeypatch.setattr` on the
    owning module, the pattern `tests/unit_tests/guard/test_guard_import_api_defects.py` uses
    for the same reason, patches exactly what this module needs and restores it unconditionally.
    """
    table = guard_eval.patch_rules(learn=False)
    monkeypatch.setattr(builtins, "compile", table["builtins.compile"](builtins.compile))
    monkeypatch.setattr(builtins, "exec", table["builtins.exec"](builtins.exec))
    monkeypatch.setattr(marshal, "loads", table["marshal.loads"](marshal.loads))
    monkeypatch.setattr(marshal, "load", table["marshal.load"](marshal.load))
    guard_api.activate_guard(())  # deny-all: no python-api=ALLOW:dynamic-code
    guard_eval.activate_guard(ImmutableDict({}), learn=False)  # no eval-* profile declared
    arm()
    try:
        yield
    finally:
        _reset_for_tests()


def test_source_to_code_called_directly_does_not_run_its_argument(_armed_with_no_eval_rule_at_all: None) -> None:
    with user_code(), pytest.raises(RuleApiPermissionError):
        importlib.abc.InspectLoader.source_to_code("MARKER = 1", "<probe>")


def test_get_code_called_directly_does_not_run_its_argument(
    _armed_with_no_eval_rule_at_all: None, tmp_path: Path
) -> None:
    module_path = tmp_path / "bypass.py"
    module_path.write_text("MARKER = 1\n", encoding="utf-8")
    loader = importlib.machinery.SourceFileLoader("bypass_probe", str(module_path))
    with user_code(), pytest.raises(RuleApiPermissionError):
        loader.get_code("bypass_probe")


def test_runsource_called_directly_does_not_run_its_argument(_armed_with_no_eval_rule_at_all: None) -> None:
    """From Python 3.13 `runsource` reports the refusal like a syntax error, so it never reaches the caller;
    before, `codeop` lets it through as an exception. Either way the code does not run."""
    interp = code.InteractiveInterpreter()
    with user_code(), contextlib.suppress(RuleApiPermissionError):
        interp.runsource("MARKER = 1")
    assert "MARKER" not in interp.locals


def test_timeit_called_directly_does_not_run_its_argument(_armed_with_no_eval_rule_at_all: None) -> None:
    with user_code(), pytest.raises(RuleApiPermissionError):
        timeit.timeit("1 + 1", number=1)


def test_run_path_called_directly_does_not_run_its_argument(
    _armed_with_no_eval_rule_at_all: None, tmp_path: Path
) -> None:
    script = tmp_path / "bypass_script.py"
    script.write_text("MARKER = 1\n", encoding="utf-8")
    with user_code(), pytest.raises(RuleApiPermissionError):
        runpy.run_path(str(script), run_name="bypass_probe")


def test_a_real_import_still_works_while_armed_with_no_eval_rule_at_all(
    _armed_with_no_eval_rule_at_all: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: the fix must not turn every import into a refused `eval-*` construct."""
    module_path = tmp_path / "ordinary_ambient_probe.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with user_code():
            module = __import__("ordinary_ambient_probe")
            assert module.VALUE == 1
    finally:
        sys.modules.pop("ordinary_ambient_probe", None)


def test_a_dataclass_is_still_generated_while_armed_with_no_eval_rule_at_all(
    _armed_with_no_eval_rule_at_all: None,
) -> None:
    """Negative control: `dataclasses`' own code generation (excluded on purpose) is untouched."""
    import dataclasses

    with user_code():

        @dataclasses.dataclass
        class Point:
            x: int
            y: int

        assert Point(1, 2).x == 1


# ------------------------------------------------------------------------------- marshal


# Built at collection time, before any test patches `compile`: a sample marshalled code
# object, the payload `marshal.loads`/`marshal.load` reconstruct without ever calling a
# guarded builtin again.
_SAMPLE_CODE_BLOB = marshal.dumps(compile("1 + 1", "<probe>", "eval"))


def test_marshal_loads_called_directly_is_refused(_armed_with_no_eval_rule_at_all: None) -> None:
    with user_code(), pytest.raises(RuleApiPermissionError):
        marshal.loads(_SAMPLE_CODE_BLOB)


def test_marshal_load_called_directly_is_refused(_armed_with_no_eval_rule_at_all: None, tmp_path: Path) -> None:
    blob_path = tmp_path / "blob.marshal"
    blob_path.write_bytes(_SAMPLE_CODE_BLOB)
    with user_code(), pytest.raises(RuleApiPermissionError), blob_path.open("rb") as handle:
        marshal.load(handle)


def test_a_real_import_with_a_pyc_cache_still_works_while_marshal_is_armed(
    _armed_with_no_eval_rule_at_all: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route `_compile_bytecode` takes to read a `.pyc` must stay ambient: it is the
    library reading its own earlier output, not the caller's.

    Forces bytecode writing regardless of the runner's own `PYTHONDONTWRITEBYTECODE`: the test
    needs a `.pyc` to exist for the second import to read back, independent of the environment
    it runs in.
    """
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    module_path = tmp_path / "pyc_cache_probe.py"
    module_path.write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with user_code():
            module = __import__("pyc_cache_probe")
            assert module.VALUE == 2
            cached = module.__cached__
            del sys.modules["pyc_cache_probe"]
            assert cached and os.path.exists(cached), "the first import must have written a .pyc to re-read"
            module = __import__("pyc_cache_probe")
            assert module.VALUE == 2
    finally:
        sys.modules.pop("pyc_cache_probe", None)


# ------------------------------------------------------------------------------- guard-rail scan

_EXCLUDED_DIR_PARTS = {"test", "tests", "idle_test", "__pycache__", "lib2to3", "ensurepip", "turtledemo"}
_EXCLUDED_FILE_PREFIXES = (
    "idlelib/",
    "turtle.py",
    "tkinter/",
    "distutils/",
    "_pyrepl/",
    "asyncio/__main__.py",
)
# pydoc.Helper.help's eval() only ever reaches 'True'/'False'/'None', gated above it; ast.parse
# is excluded via _GATEWAY_EXCLUSIONS already, listed here only for cross-reference.
_SCANNER_NOTE = "scripts/scan_gateways.py is not shipped; see wiki/audit-eval-security.md"


def _is_literal_only(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Name, ast.Attribute, ast.Call, ast.Subscript, ast.Starred)):
            return False
    return True


def _qualname_stack(stack: list[ast.AST]) -> str:
    return ".".join(n.name for n in stack if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))


def _scan_file(path: Path, rel: str) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (SyntaxError, OSError):
        return []
    findings: list[tuple[str, str]] = []
    stack: list[ast.AST] = []

    class Visitor(ast.NodeVisitor):
        def _enter(self, node: ast.AST) -> None:
            stack.append(node)
            self.generic_visit(node)
            stack.pop()

        visit_FunctionDef = _enter  # type: ignore[assignment]
        visit_AsyncFunctionDef = _enter  # type: ignore[assignment]
        visit_ClassDef = _enter  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else None
            if name in ("exec", "eval", "compile"):
                args = [*node.args, *(kw.value for kw in node.keywords)]
                if args and not _is_literal_only(args[0]):
                    findings.append((rel, _qualname_stack(stack) or "<module>"))
            self.generic_visit(node)

    Visitor().visit(tree)
    return findings


# ------------------------------------------------------------------------ wrapper mechanics


def test_wrapping_a_fresh_eval_like_builtin_produces_a_real_wrapper() -> None:
    """The idempotency check's default (`getattr(func, "__pysandbox_eval__", False)`) must read
    `False`, not `True`, for a builtin with no such attribute at all -- the ordinary case, the
    very first time a builtin is wrapped. Reading `True` there would make a fresh, unwrapped
    builtin look already-guarded and hand it straight back, unwrapped."""
    wrapped = guard_eval._wrap_eval_like(builtins.eval, qualname="builtins.eval", mode="eval")
    assert wrapped is not builtins.eval


def test_wrapping_an_already_wrapped_eval_like_builtin_is_a_no_op() -> None:
    """The idempotency check itself: wrapping the wrapper again must hand back the same object,
    not nest a second guard around it (which would, among other things, shift the frame
    `sys._getframe(1)` reads one level further from the true caller)."""
    wrapped_once = guard_eval._wrap_eval_like(builtins.eval, qualname="builtins.eval", mode="eval")
    wrapped_twice = guard_eval._wrap_eval_like(wrapped_once, qualname="builtins.eval", mode="eval")
    assert wrapped_twice is wrapped_once


def test_wrapping_an_already_wrapped_compile_is_a_no_op() -> None:
    wrapped_once = guard_eval._wrap_compile(builtins.compile)
    wrapped_twice = guard_eval._wrap_compile(wrapped_once)
    assert wrapped_twice is wrapped_once


def test_wrapping_an_already_wrapped_marshal_function_is_a_no_op() -> None:
    wrapped_once = guard_eval._wrap_marshal(marshal.loads, qualname="marshal.loads")
    wrapped_twice = guard_eval._wrap_marshal(wrapped_once, qualname="marshal.loads")
    assert wrapped_twice is wrapped_once


@pytest.mark.parametrize(
    ("original", "wrapped"),
    [
        (builtins.eval, guard_eval._wrap_eval_like(builtins.eval, qualname="builtins.eval", mode="eval")),
        (builtins.compile, guard_eval._wrap_compile(builtins.compile)),
        (marshal.loads, guard_eval._wrap_marshal(marshal.loads, qualname="marshal.loads")),
    ],
    ids=["eval", "compile", "marshal.loads"],
)
def test_a_wrapped_builtin_keeps_the_original_name_and_signature(
    original: Callable[..., Any], wrapped: Callable[..., Any]
) -> None:
    """`@guard_wraps(func)` copies `__name__`/`__doc__`/`__signature__` from the original so the
    wrapper still introspects like it, which the samples rely on; dropping the decorator leaves
    the wrapper's own literal name (`"wrapper"`) and no restored signature instead."""
    assert wrapped.__name__ == original.__name__
    assert inspect.signature(wrapped) == inspect.signature(original)


def test_eval_wrapper_reconstructs_both_positional_globals_and_locals(monkeypatch: pytest.MonkeyPatch) -> None:
    """`len(args) >= 1`/`>= 2` must stay `>=`, not `==`: a real `eval(source, g, l)` call passes
    both extra arguments positionally (`len(args) == 2`), which must still read `g` as `globals_`
    and `l` as `locals_`, not silently fall back to `frame.f_globals`/an empty `kwargs.pop`."""
    monkeypatch.setattr(guard_eval, "is_armed", lambda: False)
    wrapped = guard_eval._wrap_eval_like(builtins.eval, qualname="builtins.eval", mode="eval")
    sentinel_globals = {"__builtins__": builtins, "answer": 42}
    assert wrapped("answer", sentinel_globals, {}) == 42


def test_eval_wrapper_still_enforces_when_armed_with_no_rule_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    """`not is_armed() or is_ambient(...) or is_allowed(...)` is the unguarded passthrough; it
    must stay a passthrough only while *not* armed, never while armed. Forcing every other
    disjunct False isolates `is_armed()` itself: armed, not ambient, not allowed must still reach
    the refusal, not fall through to the raw builtin."""
    monkeypatch.setattr(guard_eval, "is_armed", lambda: True)
    monkeypatch.setattr(guard_eval, "is_ambient", lambda frame: False)
    monkeypatch.setattr(guard_eval.guard_api, "is_allowed", lambda name: False)
    monkeypatch.setattr(guard_eval, "_profiles", ImmutableDict({}))
    wrapped = guard_eval._wrap_eval_like(builtins.eval, qualname="builtins.eval", mode="eval")
    with pytest.raises(RuleApiPermissionError):
        wrapped("1 + 1")


def test_every_stdlib_exec_eval_compile_gateway_is_covered_or_excluded() -> None:
    """Re-runs the AST scan that built `_GATEWAYS` against the interpreter actually running this
    test, so a Python release that adds a new exec/eval/compile call with a non-literal argument
    fails this test instead of silently reopening the bypass `wiki/weaknesses.md` records fixed.

    The scan cannot see a call made by passing the builtin by reference instead of naming it
    (`importlib._bootstrap._call_with_frames_removed(compile, ...)`): those three entries are
    documented, not covered, by this test, and are unit-tested directly above instead.
    """
    roots = {sysconfig.get_paths()["stdlib"]}
    platstdlib = sysconfig.get_paths().get("platstdlib")
    if platstdlib:
        roots.add(platstdlib)

    uncovered: list[tuple[str, str]] = []
    for root in roots:
        root_path = Path(root)
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIR_PARTS and not d.startswith(".")]
            if "site-packages" in dirpath or "dist-packages" in dirpath:
                continue
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                full = Path(dirpath) / fname
                rel = full.relative_to(root_path).as_posix()
                if rel.startswith(_EXCLUDED_FILE_PREFIXES):
                    continue
                for rel_found, qualname in _scan_file(full, rel):
                    top_level_dir = rel_found.split("/", 1)[0] + "/" if "/" in rel_found else ""
                    if (
                        rel_found in _GATEWAY_FILES
                        or (rel_found, qualname) in _GATEWAYS
                        or (rel_found, qualname) in _GATEWAY_EXCLUSIONS
                        or top_level_dir in _EXCLUDED_FILE_PREFIXES
                    ):
                        continue
                    uncovered.append((rel_found, qualname))

    assert not uncovered, (
        f"new exec/eval/compile gateway(s) found on {sys.version.split()[0]}, "
        f"neither in _GATEWAYS/_GATEWAY_FILES nor in _GATEWAY_EXCLUSIONS: {sorted(set(uncovered))} "
        f"({_SCANNER_NOTE})"
    )
