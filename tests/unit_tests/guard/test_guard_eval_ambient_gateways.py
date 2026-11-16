# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`is_ambient`'s gateway walk: stdlib entry points that run caller-supplied code directly.

`importlib.abc.InspectLoader.source_to_code`, `SourceFileLoader.get_code`,
`code.InteractiveInterpreter.runsource`, `timeit.timeit` and `runpy.run_path` each reach
`compile`/`exec` from inside a stdlib frame, which the old single-frame `is_ambient` always
trusted. Calling one of them directly, with no `eval-*` rule declared and no
`python-api=ALLOW:dynamic-code` grant, used to run the application's own source unguarded; see
`wiki/weaknesses.md`. The integration tests below pin the fix behaviourally (the dangerous
`exec`/`compile` must not have run, not merely "an exception was raised": `runsource` catches
`RuleApiPermissionError` the same broad way it catches a real `SyntaxError`). The pure tests pin
the walk itself against a synthetic frame chain, independent of any guard activation.
"""

import ast
import builtins
import code
import importlib.abc
import importlib.machinery
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
    """`runsource` catches `Exception` broadly to report a syntax error, the same way it would
    a real one: the refusal never reaches the caller as an exception, only as the absence of the
    effect `exec` would have had."""
    interp = code.InteractiveInterpreter()
    with user_code():
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
    library reading its own earlier output, not the caller's."""
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
