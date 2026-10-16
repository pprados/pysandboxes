# `eval-*` security assessment

This report assesses attacker-controlled source passed to `eval`, `exec`,
`compile`, or `guarded_eval`. It covers the `eval-*` sub-language and runtime
helpers, not arbitrary bytecode. Python patching and OS isolation are separate
boundaries; see [Python-layer assessment](audit-python-security.md) and
[OS providers](os-providers.md).

## Controls and evidence

`pysandboxes/eval_transform.py` validates and rewrites permitted syntax.
`pysandboxes/guard_eval.py::build_namespace` creates the evaluation namespace
and merges caller-provided `names`. `pysandboxes/eval_runtime.py` implements
attribute checks, selected operator checks, budgets, and guarded stores. The
code executes in the host process; no `eval-*` rule is an OS boundary.

The findings marked reproduced below come from in-memory probes run during the
2026-10-16 audit; there is no committed probe file. The task ledger records a
unit checkpoint of 3,689 passed, 20 skipped, 6 xfailed on Python 3.14.5. Tests
cited here cover specific regression cases and do not establish universal
safety.

## Findings

| Attack or behavior | Control path and evidence | Result, prerequisites, limits |
|---|---|---|
| Override injected `__sb_getattr__` through `names` | `pysandboxes/guard_eval.py::build_namespace` merges `HELPERS`, then `names`. In-memory probe: `run_guarded('g.gi_frame.f_globals', rules, namespace={**HELPERS, 'g': gen, '__sb_getattr__': getattr})`, without eval attribute/magic grants. | **Reproduced policy bypass.** The supplied mapping replaces the frame-checking helper, exposing generator caller globals. Requires caller control of the namespace/`names` mapping; source-string control alone does not supply this entry. Frame denial applies only while the intended helper runs. This exposes host-process state; the probe does not establish escape from an OS boundary. |
| Mutate supplied mutable objects | `pysandboxes/eval_runtime.py::__sb_binop__` applies in-place operators; `__sb_writable__` checks identity only on guarded subscript stores. In-memory probe: `__sb_binop__('+=', input_list, [2])` returns and mutates the original; a nested list inside a supplied object also passes the identity test for nested store. | **Reproduced integrity/policy issue.** Requires the application to pass mutable objects. Top-level rebinding protection does not prevent in-place mutation, and supplied objects are not recursively registered. Related committed tests: `tests/unit_tests/guard/test_eval_defects.py::test_an_augmented_assignment_still_works_in_place` and `tests/unit_tests/guard/test_guard_eval.py::test_an_object_the_application_supplied_is_not_written_by_subscript`; direct-store tests do not prove nested or in-place safety. Not an OS boundary escape. |
| Numeric multiplication exceeds `eval-max-alloc` | `pysandboxes/eval_runtime.py::__sb_binop__` checks `*` when an operand is a sequence; integer multiplication reaches the operator without a bit-size check. In-memory probe: with `eval-max-alloc=1000`, build powers and multiply integers until the result occupies 2,000 bytes; no refusal occurs. | **Reproduced allocation-budget bypass.** Applies to integer multiplication; sequence repetition is checked. This is a denial-of-service/resource risk, not by itself a policy or host-boundary escape. `tests/unit_tests/guard/test_eval_runtime.py::test_binop_refuses_a_huge_power_before_computing` exercises exponentiation, not numeric multiplication. |
| Custom exception hooks during parent reconstruction | Restricted exception reconstruction is in `pysandboxes/remote/tools.py`. In-memory probes: preload a matching custom `Exception` class in the parent, then reconstruct a crafted exception with side-effecting `__setstate__`; the hook executes. Fallback descriptor reconstruction also calls custom `__new__`. | **Reproduced conditional parent-side execution.** Requires the custom class to be preloaded/resolvable and a hostile remote exception payload to reach reconstruction. This does not mean arbitrary exception classes are always importable, but class constructors/state hooks are executable code. It runs in the parent, so an OS boundary around the child does not prevent it. `tests/unit_tests/remote/test_restricted_unpickle.py` covers intended allow/deny and fallback behavior; it is not evidence hooks are inert. This IPC finding is separate from `eval-*`. |
| Oversized sequence arithmetic and format widths | `eval_runtime.__sb_binop__`, `__sb_format__`, `check_format_spec`, and format-template validation check selected allocation sources before operating. | Large powers, sequence repetition/concatenation, shifts and formatting have targeted checks in `tests/unit_tests/guard/test_eval_runtime.py` and `test_eval_defects.py`. Checks cover rewritten/known operations, not every constructor or third-party callable. Unchecked native work can cause denial of service. |
| Attribute/frame traversal with the intended helper | `eval_runtime.__sb_getattr__` calls `_check_attr`; `FRAME_CAPTURE` denies listed frame/code attributes. Guarded builtins and formatting helpers route through checks. | Specific paths are tested in `tests/unit_tests/guard/test_eval_runtime.py` and `test_eval_hardening.py`. The `names` override finding means it is inaccurate to claim every attribute read always passes the helper when callers control that mapping. |
| Caller-supplied callables and namespace modes | `build_namespace` exposes permitted builtins and wrapper names; `eval-namespace=caller` is an explicit broader mode. | A callable supplied by the application runs application-selected behavior. Adaptive/caller namespace choices enlarge ambient capability. These are conditional capabilities and policy concerns; they do not themselves demonstrate escape from an OS sandbox. |
| Time, iterations, recursion, native work | `eval_runtime` injects ticks and call-depth checks; `guard_eval` uses a timeout worker. | Timeout and iteration cases are in `tests/unit_tests/guard/test_guard_eval.py`. Native/C-level work may not reach a tick, and a Python worker thread cannot safely preempt arbitrary native work. This is a denial-of-service/resource containment limit. A killable process boundary is needed where supported. |

## Boundary statement

The `eval-*` sub-language reduces accidental and source-level capability
access. It does not prove untrusted input cannot affect host state: caller-
controlled mappings can replace runtime helpers, mutable inputs can be changed
in place or through nested references, and allocation checks do not cover all
native work. Keep mappings and supplied objects narrow. For deliberate hostile
code, use an appropriately configured OS-backed provider and treat
parent-side IPC reconstruction as a separate trust boundary. `os-sandbox=none`
and `os-sandbox=subprocess` provide no OS security boundary.
