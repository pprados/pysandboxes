import inspect
import pickle
from types import ModuleType
from typing import Any, Dict, Set, Tuple

import pytest

from pysandboxes import RuleAttributeError


def test_escape_with_closure() -> None:
    # Find the _original version of io.open (possible if the code is in Python)
    import io

    assert hasattr(io.open, "__closure__"), "Not in a pysandbox"
    original_open = io.open.__closure__[0].cell_contents  # type: ignore[index]
    assert original_open.__module__ in ["_io", "io"], "Not the _original io.open"


@pytest.mark.skip
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


@pytest.mark.skip
def test_escape_with_meta_path() -> None:
    import sys

    with pytest.raises(RuleAttributeError):
        new_list = list(sys.meta_path)[1:]
        sys.meta_path = new_list


@pytest.mark.skip(reason="escape via pickle deserialization not yet blocked")
def test_escape_with_pickle() -> None:
    # Pickle bypass: pickle.loads() uses the stack-based VM to deserialize objects
    # The GLOBAL opcode (c in text protocol) bypasses import restrictions.
    # Pickle extracts os.system directly from the interpreter's module cache.
    # Attack: craft a pickle payload that calls os.system("dangerous_command")
    # https://docs.python.org/3/library/pickle.html
    # See: https://intoli.com/blog/dangerous-pickle/

    # Construct pickle bytecode that loads os.system
    # Protocol format: GLOBAL opcode (c) imports module.function
    # c<module>\n<function>\n  →  loads and pushes module.function onto stack
    # R  →  reduces (calls) with empty args
    malicious_pickle = b"cos\nsystem\np0\n(S'echo pwned'\ntRp1\n."

    # If sandbox allows pickle, unpickling this should fail with RuleAttributeError
    with pytest.raises(RuleAttributeError):
        pickle.loads(malicious_pickle)  # type: ignore[arg-type]


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
