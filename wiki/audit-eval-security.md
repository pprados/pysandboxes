# `eval-*` security assessment

This report assesses attacker-controlled source passed to `eval`, `exec`,
`compile`, or `guarded_eval`. It covers the `eval-*` sub-language and runtime
helpers, not arbitrary bytecode. Python patching and OS isolation are separate
boundaries; see [Python-layer assessment](audit-python-security.md) and
[OS providers](os-providers.md).

## Controls and evidence

`pysandboxes/eval_transform.py` validates and rewrites syntax.
`pysandboxes/guard_eval.py::build_namespace` creates the namespace and merges
caller-provided `names`. `pysandboxes/eval_runtime.py` checks attributes and
selected operators, enforces budgets, and guards stores. Evaluation runs in
the host process; `eval-*` is not an OS boundary.

The findings marked reproduced below come from in-memory probes run during the
2026-10-16 audit; there is no committed probe file. On 2026-11-13, at commit
`2601d77b` (release 0.12.0), the first three were replayed with real
`guard_eval.guarded_eval` calls under a permissive profile built with
`eval_rules.parse_rules` (Python 3.14.10), each with a negative control. All three
reproduced:

- `names={"__sb_getattr__": getattr}` turns the refusal `'gi_frame' is denied by the eval guard`
  into a returned dict holding the caller's globals (`__name__` present).
- `a += [2]` run in `exec` mode on a supplied list leaves `[1, 2]`, and `a[0][0] = 9` on a
  supplied nested list leaves `[[9]]`. The direct store `a[0] = 9` is refused
  (`'list[...] =' is denied`), so the control holds.
- With `eval-max-alloc=1000`, `(1 << 7900) * (1 << 7900)` returns a 1,976-byte integer, while
  `[0] * 5000` is refused (`a 5000-element repetition exceeds eval-max-alloc=1000`).

The fourth finding (exception hooks in the parent) was replayed the same day with
`tools.from_b85_restricted`. A class `AppError(Exception)` with a `__setstate__` was registered in
`sys.modules` under a module name, and an instance with a non-empty `__dict__` was pickled.
Under `exception_predicate` the payload was accepted and `__setstate__` ran (its write
to a flag file raised `OSError` because the probe's sandbox is read-only there, which is the proof the hook
executed). Under `descriptor_predicate` the same payload was refused (`preloaded_app.AppError is refused by the
sandbox transport guard`). `rebuild_from_descriptor` on a descriptor naming the same class returned an `AppError`
without running `__setstate__`. A custom `__new__` was not probed; that part stays a code reading. The probe
scripts were kept outside the repository.
Tests cited here cover specific regression cases and do not establish universal
safety.

## Findings

| Attack or behavior | Control path and evidence | Result, prerequisites, limits |
|---|---|---|
| Override injected `__sb_getattr__` through `names` | `pysandboxes/guard_eval.py::build_namespace` merges `HELPERS`, then `names`. In-memory probe: `run_guarded('g.gi_frame.f_globals', rules, namespace={**HELPERS, 'g': gen, '__sb_getattr__': getattr})`, without eval attribute/magic grants. | **Reproduced policy bypass.** The supplied mapping replaces the frame-checking helper, exposing generator caller globals. Requires caller control of the namespace/`names` mapping; source-string control alone does not supply this entry. Frame denial applies only while the intended helper runs. This exposes host-process state; the probe does not establish escape from an OS boundary. |
| Mutate supplied mutable objects | `pysandboxes/eval_runtime.py::__sb_binop__` applies in-place operators; `__sb_writable__` checks identity only on guarded subscript stores. In-memory probe: `__sb_binop__('+=', input_list, [2])` returns and mutates the original; a nested list inside a supplied object also passes the identity test for nested store. | **Reproduced integrity/policy issue.** Requires the application to pass mutable objects. Top-level rebinding protection does not prevent in-place mutation, and supplied objects are not recursively registered. Related committed tests: `tests/unit_tests/guard/test_eval_defects.py::test_an_augmented_assignment_still_works_in_place` and `tests/unit_tests/guard/test_guard_eval.py::test_an_object_the_application_supplied_is_not_written_by_subscript`; direct-store tests do not prove nested or in-place safety. Not an OS boundary escape. |
| Numeric multiplication exceeds `eval-max-alloc` | `pysandboxes/eval_runtime.py::__sb_binop__` checks `*` when an operand is a sequence; integer multiplication reaches the operator without a bit-size check. In-memory probe: with `eval-max-alloc=1000`, build powers and multiply integers until the result occupies 2,000 bytes; no refusal occurs. | **Reproduced allocation-budget bypass.** Applies to integer multiplication; sequence repetition is checked. This is a denial-of-service/resource risk, not by itself a policy or host-boundary escape. `tests/unit_tests/guard/test_eval_runtime.py::test_binop_refuses_a_huge_power_before_computing` exercises exponentiation, not numeric multiplication. |
| Custom exception hooks during parent reconstruction | Restricted exception reconstruction is in `pysandboxes/remote/tools.py`. In-memory probes: preload a matching custom `Exception` class in the parent, then reconstruct a crafted exception with side-effecting `__setstate__`; the hook executes. Fallback descriptor reconstruction also calls custom `__new__`. | **Reproduced conditional parent-side execution (replayed 2026-11-13 at `2601d77b`, rich channel only).** Requires the custom class to be preloaded/resolvable and a hostile remote exception payload to reach reconstruction. The fallback descriptor channel refused the pickled class and did not run `__setstate__`; its call to a custom `__new__` is by code reading only. This does not mean arbitrary exception classes are always importable, but class constructors/state hooks are executable code. It runs in the parent, so an OS boundary around the child does not prevent it. `tests/unit_tests/remote/test_restricted_unpickle.py` covers intended allow/deny and fallback behavior; it is not evidence hooks are inert. This IPC finding is separate from `eval-*`. |
| Oversized sequence arithmetic and format widths | `eval_runtime.__sb_binop__`, `__sb_format__`, `check_format_spec`, and format-template validation check selected allocation sources before operating. | Large powers, sequence repetition/concatenation, shifts and formatting have targeted checks in `tests/unit_tests/guard/test_eval_runtime.py` and `test_eval_defects.py`. Checks cover rewritten/known operations, not every constructor or third-party callable. Unchecked native work can cause denial of service. |
| Attribute/frame traversal with the intended helper | `eval_runtime.__sb_getattr__` calls `_check_attr`; `FRAME_CAPTURE` denies listed frame/code attributes. Guarded builtins and formatting helpers route through checks. | Specific paths are tested in `tests/unit_tests/guard/test_eval_runtime.py` and `test_eval_hardening.py`. The `names` override finding means it is inaccurate to claim every attribute read always passes the helper when callers control that mapping. |
| Caller-supplied callables and namespace modes | `build_namespace` exposes permitted builtins and wrapper names; `eval-namespace=caller` is an explicit broader mode. | A callable supplied by the application runs application-selected behavior. Adaptive/caller namespace choices enlarge ambient capability. These are conditional capabilities and policy concerns; they do not themselves demonstrate escape from an OS sandbox. |
| Time, iterations, recursion, native work | `eval_runtime` injects ticks and call-depth checks; `guard_eval` uses a timeout worker. | Timeout and iteration cases are in `tests/unit_tests/guard/test_guard_eval.py`. Native/C-level work may not reach a tick, and a Python worker thread cannot safely preempt arbitrary native work. This is a denial-of-service/resource containment limit. A killable process boundary is needed where supported. |
| Regular-expression backtracking | `eval_runtime._warn_about_regex` logs one warning per attribute name when evaluated code reaches `re` or a compiled pattern; the source states that a match is one opaque C call that charges no tick and holds the GIL. | **Established by code, documented by the project, not reproduced here.** A pattern such as `(a+)+` can run past `eval-timeout` while holding the whole interpreter, host application included. The guard warns and does not refuse. The mitigation is for the application to inject a linear engine under the name `re`. Denial of service only. |
| Workers blocked in native calls | `guard_eval.run_guarded` refuses a new evaluation once `leaked_threads()` reaches `eval-max-leaked-threads`, raising `EvalInterrupted`. | **Established by code.** An evaluation that blocks in a C call and outlives its timeout keeps running. The counter bounds how many such workers accumulate; it does not stop one. Denial of service only. |
| Library code generation exempt from the checks | `guard_eval.is_ambient` exempts the runtime's own `compile`, `exec` and `eval` calls (`dataclasses`, `typing`, `importlib`), keyed on the caller's code-object filename under the stdlib and `site-packages`, not on a module name. | **Established by code, not probed for a bypass.** The filename can only be set through `compile()`, which is itself guarded and absent from the closed namespace. A caller that can place a file under `site-packages` or the stdlib, or one that supplies a namespace with `eval-namespace=caller`, is outside this model. |
| Nested supplied objects and in-place operators (status check) | `__sb_writable__` compares identity against the objects found at the top level of `names`; its docstring says an object nested in a supplied one is not covered. | **Established by code, unchanged since 2026-10-16.** The mitigation is on the application side: pass copies, or immutable values, and keep `names` narrow. |

## Boundary statement

The `eval-*` sub-language reduces accidental and source-level capability
access. It does not prove untrusted input cannot affect host state: caller-
controlled mappings can replace runtime helpers, mutable inputs can be changed
in place or through nested references, and allocation checks do not cover all
native work. Keep mappings and supplied objects narrow. For deliberate hostile
code, use an appropriately configured OS-backed provider and treat
parent-side IPC reconstruction as a separate trust boundary. `os-sandbox=none`
and `os-sandbox=subprocess` provide no OS security boundary.
