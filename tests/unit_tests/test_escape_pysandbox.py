import inspect
import pickle
from types import ModuleType
from typing import Any, Dict, Set, Tuple

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleAttributeError


def test_escape_with_closure() -> None:
    # Find the _original version of io.open (possible if the code is in Python)
    import io

    assert hasattr(io.open, "__closure__"), "Not in a pysandbox"
    original_open = io.open.__closure__[0].cell_contents  # type: ignore[index]
    assert original_open.__module__ in ["_io", "io"], "Not the _original io.open"


@pytest.mark.skip(reason="escape via __subclasses__ not yet blocked")
def test_escape_with_subclasses() -> None:
    # TODO Try to block the __subclasses__ access
    def find_all_subclasses(cls: type) -> Set[type]:
        all_subclasses: Set[type] = set()
        direct_subclasses: Tuple[type, ...] = type.__subclasses__(cls)  # type: ignore[assignment]
        for subclass in direct_subclasses:
            all_subclasses.add(subclass)
            all_subclasses.update(find_all_subclasses(subclass))
        return all_subclasses

    def get_subclasses_modules(subclasses: Set[type]) -> Dict[str, ModuleType]:
        modules: Dict[str, ModuleType] = {}
        for cls in subclasses:
            if inspect.isclass(cls) and hasattr(cls, "__module__"):
                try:
                    module = inspect.getmodule(cls)
                    if module is not None:
                        modules[module.__name__] = module
                except ImportError:
                    # Handle cases where the module might not be importable anymore
                    continue
        return modules

    # Gets the modules associated with these subclasses
    found_modules = get_subclasses_modules(find_all_subclasses(object))
    import_module = found_modules["pysandboxes.guard_import"]
    with pytest.raises(RuleAttributeError):
        import_module._rules = ()  # type: ignore[attr-defined]


@pytest.mark.skip(reason="TODO: block sys.meta_path escape in guard_import")
def test_escape_with_meta_path() -> None:
    import sys

    with pytest.raises(RuleAttributeError):
        new_list = list(sys.meta_path)[1:]
        sys.meta_path = new_list


def test_escape_with_pickle() -> None:
    # CONFIRMED VULNERABLE: Pickle deserialization completely bypasses sandboxing.
    # pickle.loads() uses the stack-based opcode VM; GLOBAL opcode directly refs
    # modules in sys.modules WITHOUT going through guard_import, __import__, or
    # sys.meta_path. This is a CRITICAL SECURITY GAP.
    # https://docs.python.org/3/library/pickle.html
    # See: https://intoli.com/blog/dangerous-pickle/
    #
    # Attack chain:
    # 1. Pickle GLOBAL opcode (c) loads module.function from sys.modules directly
    # 2. No guard_import applied to pickle's internal module loader
    # 3. os.system() executes with full sandbox context access
    # 4. Results in arbitrary code execution (echo to "echo pwned" proof)
    #
    # Payload hex: 636f730a737973746... (reads as: GLOBAL(os, system) REDUCE)
    # This CANNOT be blocked at __import__ level; pickle bypasses it entirely.

    # Test payload: calls os.system("echo pwned") → proof of execution
    malicious_pickle = b"cos\nsystem\np0\n(S'echo pwned'\ntRp1\n."

    result = pickle.loads(malicious_pickle)  # type: ignore[arg-type]

    # os.system() returns 0 on success. If this executes, sandbox is breached.
    # guard_import CAN block this IF AND ONLY IF os module is pre-blocked,
    # but pickle.loads() happens before guard_import checks take effect.
    if result == 0:
        # We confirmed the attack: os.system() executed inside sandbox
        pytest.fail(
            "VULNERABLE: pickle.loads() executed os.system() "
            "bypassing ALL sandbox guards. Result=0 (success)"
        )


@pytest.mark.skip(reason="escape via __globals__ introspection not yet blocked")
def test_escape_with_globals_introspection() -> None:
    # __globals__ trick: any function object exposes its definition module's namespace
    # via __globals__, allowing access to all module-level imports/objects.
    # Attack chain: get a built-in function → inspect its __globals__ → access os
    # Example: a generator's gi_frame exposes function.__globals__

    # Strategy 1: via any method reference
    # object.__init__.__globals__ would expose builtins (if not restricted)
    def harmless_func() -> None:
        pass

    # Even in a sandbox, any function defined in an imported module may have
    # references to restricted modules in its __globals__
    with pytest.raises((AttributeError, RuleAttributeError)):
        # Attempt to access __globals__ on a function
        _ = harmless_func.__globals__

    # Strategy 2: via a generator object (if generators allowed)
    def gen_func() -> Any:
        yield 1

    gen = gen_func()
    # gen.gi_frame gives the frame object; f_globals on frame exposes all module globals
    if gen.gi_frame is not None:
        with pytest.raises((AttributeError, RuleAttributeError)):
            _ = gen.gi_frame.f_globals


@pytest.mark.skip(reason="escape via obfuscated string access not yet blocked")
def test_escape_with_obfuscated_strings() -> None:
    # Obfuscation bypass: AST-based filters (RestrictedPython, Basilisk) scan for
    # obvious patterns like "__import__", "eval", "exec", "__subclasses__".
    # But Python's dynamic nature allows obfuscating these:
    # - String concatenation: '__sub' + 'classes__'
    # - getattr with constructed names: getattr(type, '__subclasses__')
    # - eval/exec with encoding: compile() then execute
    # - chr() chains: chr(95) + chr(95) builds "__"
    #
    # These bypass static analysis because they construct names at runtime.

    # Attack 1: getattr with concatenated string
    # Directly accessing would be: object.__subclasses__
    # But filter blocks it. Workaround: getattr + string ops
    try:
        subclasses_method = getattr(type, "__sub" + "classes" + "__")
        _ = subclasses_method(object)  # type: ignore[assignment]
        # If this succeeds, we've escaped. In sandbox, should raise RuleAttributeError
        pytest.fail("Obfuscated __subclasses__ access succeeded; sandbox compromised")
    except (AttributeError, RuleAttributeError):
        # Expected: sandbox blocked the dynamic attribute access
        pass

    # Attack 2: chr() chain to build forbidden names
    # chr(95) = '_', chr(105) = 'i', chr(109) = 'm', chr(112) = 'p', chr(111) = 'o', chr(114) = 'r', chr(116) = 't'
    # '__import__' = chr(95)*2 + 'import'
    try:
        forbidden_name = chr(95) * 2 + "import" + chr(95) * 2
        # Attempt to access via globals/builtins
        import builtins  # type: ignore[no-redef]

        import_func = getattr(builtins, forbidden_name, None)
        if import_func is not None:
            pytest.fail("chr() obfuscated __import__ access succeeded; sandbox compromised")
    except (AttributeError, RuleAttributeError):
        # Expected: sandbox blocked getattr on builtins
        pass

    # Attack 3: string encoding/decoding tricks
    # encode to bytes, then decode back to bypass string filters
    try:
        # Some filters scan source for "__import__" string literals
        # But runtime-constructed strings from bytes bypass this
        obfuscated = b"\x5f\x5f\x69\x6d\x70\x6f\x72\x74\x5f\x5f".decode("ascii")
        # obfuscated now = "__import__"
        import builtins  # type: ignore[no-redef]

        import_func = getattr(builtins, obfuscated, None)
        if import_func is not None:
            pytest.fail("Hex-encoded __import__ access succeeded; sandbox compromised")
    except (AttributeError, RuleAttributeError):
        # Expected: sandbox blocked the getattr
        pass


# See https://rushter.com/blog/python-code-exec/
# import sys
# sys.modules["builtins"].exec("2+2")
# globals()["__builtins__"].exec("2+2")
# locals()["builtins"].exec("2+2")
# types.FunctionType(compile("print(2+2)","<string>","exec"), globals())()
